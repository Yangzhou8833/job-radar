"""Your applications: pipeline status, timeline, reminders and funnel.

data/applications.csv holds one row per application (open it in Excel if you like), and
data/application_events.jsonl one line per status change, so every application has a
dated timeline and the funnel can tell how far each one got.

Status vocabulary (same spellings as the ai-job-search tracker, underscores only):

    drafted -> applied -> interview -> offer -> hired
    closed:  rejected | no_response | offer_declined | withdrawn

`stage` says where inside a status you are ("HR screen", "Round 2", "Case study"),
`next_date` is the next interview or the application deadline, and `reason` is why an
application closed. The legacy spellings "no response" / "offer declined" are read as
no_response / offer_declined.
"""
import csv
import datetime
import json
import os
import statistics

from . import config, countries
from .rules import norm_key

STATUSES = ("drafted", "applied", "interview", "offer", "hired", "rejected", "no_response", "offer_declined", "withdrawn")
FINAL = ("hired", "rejected", "no_response", "offer_declined", "withdrawn")
LEGACY = {"no response": "no_response", "offer declined": "offer_declined"}
RANK = {"drafted": 0, "applied": 1, "interview": 2, "offer": 3, "hired": 4, "offer_declined": 3}
FUNNEL = ("applied", "interview", "offer", "hired")
FIELDS = ["id", "date", "company", "role", "status", "stage", "next_date", "contact", "salary", "cv_version",
          "reason", "job_key", "source", "notes", "updated"]
EDITABLE = ("stage", "next_date", "contact", "salary", "cv_version", "reason", "notes", "source", "date")
EVENTS = "application_events.jsonl"


def today():
    return datetime.date.today().isoformat()


def normalize_status(status):
    s = (status or "").strip().lower()
    s = LEGACY.get(s, s)
    if s not in STATUSES:
        raise ValueError(f"unknown application status {status!r}; use one of {', '.join(STATUSES)}")
    return s


def app_id(company, role):
    return norm_key(company, role)


# ---------------------------------------------------------------- storage
def load():
    path = config.data(config.TRACKER)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["id"] = r.get("id") or app_id(r.get("company"), r.get("role"))
        try:
            r["status"] = normalize_status(r.get("status") or "applied")
        except ValueError:
            pass  # keep an unknown value visible rather than dropping the row
    return rows


def save(rows):
    os.makedirs(config.data_dir(), exist_ok=True)
    path = config.data(config.TRACKER)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") or "" for k in FIELDS})
    os.replace(tmp, path)


def load_events():
    path = config.data(EVENTS)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def add_event(event):
    os.makedirs(config.data_dir(), exist_ok=True)
    with open(config.data(EVENTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def find(rows, ident):
    """The row with this id, also accepting a raw "Company|Role" pair."""
    ident = (ident or "").strip()
    wanted = {ident.lower()}
    if "|" in ident:
        wanted.add(app_id(*ident.split("|", 1)))
    return next((r for r in rows if r["id"] in wanted), None)


# ---------------------------------------------------------------- changes
def set_status(rows, ident, status, stage=None, note="", reason=None, when=None):
    """Move one application to `status`, record the change, return the row."""
    when = when or today()
    row = find(rows, ident)
    if row is None:
        raise KeyError(f"no application {ident!r}")
    new = normalize_status(status)
    old = row.get("status") or ""
    if stage is not None:
        row["stage"] = stage
    if reason is not None:
        row["reason"] = reason
    if new != old or stage or note:
        add_event({"id": row["id"], "at": when, "from": old, "to": new, "stage": stage or "", "note": note or ""})
    row["status"] = new
    row["updated"] = when
    if RANK.get(new, 1) >= 1 and new != "drafted" and not row.get("date"):
        row["date"] = when
    return row


def update_fields(rows, ident, fields, when=None):
    row = find(rows, ident)
    if row is None:
        raise KeyError(f"no application {ident!r}")
    for k, v in fields.items():
        if k in EDITABLE:
            row[k] = (str(v) if v is not None else "").strip()
    row["updated"] = when or today()
    return row


def create(rows, company, role, status="applied", source="", job_key="", notes="", when=None):
    """Add an application (or return the existing one with the same company + role)."""
    when = when or today()
    ident = app_id(company, role)
    row = find(rows, ident)
    if row:
        return row, False
    row = {k: "" for k in FIELDS}
    status = normalize_status(status)
    row.update(id=ident, company=company, role=role, status=status, source=source, job_key=job_key, notes=notes,
               date="" if status == "drafted" else when, updated=when)
    rows.append(row)
    add_event({"id": ident, "at": when, "from": "", "to": row["status"], "stage": "", "note": "created"})
    return row, True


def upsert_from_job(rows, key, v, status="applied", when=None):
    """A job marked on the dashboard: create its application, or move it forward (never back)."""
    row, created = create(rows, v.get("company", ""), v.get("title", ""), status=status, source=v.get("url", ""),
                          job_key=key, notes="from dashboard", when=when)
    if not row.get("job_key"):
        row["job_key"] = key
    if not created and RANK.get(normalize_status(status), 0) > RANK.get(row["status"], 0) and row["status"] not in FINAL:
        set_status(rows, row["id"], status, when=when)
        return row, "moved to " + status
    return row, "added" if created else "already tracked"


# ---------------------------------------------------------------- reading the pipeline
def reached(row, events):
    """Highest funnel stage this application got to (0 drafted ... 4 hired)."""
    best = RANK.get(row.get("status"), 0)
    for e in events:
        if e.get("id") == row["id"]:
            best = max(best, RANK.get(e.get("to"), 0))
    if row.get("status") in ("rejected", "no_response", "withdrawn") and best == 0:
        best = 1  # closed without a recorded history: it was at least sent
    return best


def last_activity(row, events):
    dates = [e["at"] for e in events if e.get("id") == row["id"] and e.get("at")]
    return max(dates + [row.get("updated") or "", row.get("date") or ""]) or None


def _days(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def reminders(rows, events, profile=None, on=None):
    """What needs attention today: follow-ups, closing silent applications, upcoming dates."""
    on = on or today()
    t = (profile.raw.get("tracking", {}) if profile else {})
    follow, silent, soon = int(t.get("follow_up_days", 14)), int(t.get("no_response_days", 30)), int(t.get("upcoming_days", 3))
    out = []
    for r in rows:
        status, nd = r.get("status"), r.get("next_date") or ""
        base = {"id": r["id"], "company": r.get("company"), "role": r.get("role")}
        if nd:
            try:
                d = _days(on, nd)
            except ValueError:
                d = None
            if d is not None:
                if status in ("interview", "offer") and 0 <= d <= soon:
                    out.append({**base, "kind": "upcoming", "days": d, "text": f"{r.get('stage') or status} in {d} day(s)" if d else f"{r.get('stage') or status} today"})
                elif status == "interview" and d < 0:
                    out.append({**base, "kind": "update", "days": -d, "text": "interview date passed: record the outcome"})
                elif status == "drafted" and 0 <= d <= soon:
                    out.append({**base, "kind": "deadline", "days": d, "text": f"application deadline in {d} day(s)"})
        if status == "applied":
            last = last_activity(r, events)
            try:
                quiet = _days(last, on) if last else None
            except ValueError:
                quiet = None
            if quiet is not None and quiet >= silent:
                out.append({**base, "kind": "no_response", "days": quiet, "text": f"no reply for {quiet} days: mark as no response?"})
            elif quiet is not None and quiet >= follow:
                out.append({**base, "kind": "follow_up", "days": quiet, "text": f"no reply for {quiet} days: time to follow up"})
    order = {"upcoming": 0, "deadline": 1, "update": 2, "follow_up": 3, "no_response": 4}
    return sorted(out, key=lambda x: (order[x["kind"]], x["days"]))


def funnel(rows, events, seen=None, profile=None):
    """Applied -> interview -> offer -> hired, overall and split by source, fit, country, direction."""
    from .dashboard import SOURCE_LABELS
    seen = seen or {}
    sent = [r for r in rows if reached(r, events) >= 1]

    def counts(group):
        c = {s: 0 for s in FUNNEL}
        for r in group:
            lvl = reached(r, events)
            for i, s in enumerate(FUNNEL, start=1):
                if lvl >= i:
                    c[s] += 1
        c["interview_rate"] = round(100 * c["interview"] / c["applied"]) if c["applied"] else None
        return c

    def dims(r):
        v = seen.get(r.get("job_key")) or {}
        title = v.get("title") or r.get("role") or ""
        dirs = (profile.families_of(title) if profile else []) or ["other"]
        return {"source": SOURCE_LABELS.get(v.get("portal"), v.get("portal") or "added by hand"),
                "fit": v.get("rank_fit") or "unranked",
                "country": countries.workable_name(v["country"]) if v.get("country") in countries.COUNTRIES else "unknown",
                "direction": dirs[0].replace("_", " ")}

    by = {}
    for dim in ("source", "fit", "country", "direction"):
        groups = {}
        for r in sent:
            groups.setdefault(dims(r)[dim], []).append(r)
        by[dim] = sorted(({"label": k, **counts(g)} for k, g in groups.items()), key=lambda x: -x["applied"])

    waits = []
    for r in sent:
        applied_on = r.get("date")
        later = sorted(e["at"] for e in events if e.get("id") == r["id"] and e.get("to") not in ("applied", "drafted", "")
                       and e.get("at"))
        if applied_on and later:
            try:
                waits.append(_days(applied_on, later[0]))
            except ValueError:
                pass
    status_counts = {s: sum(r.get("status") == s for r in rows) for s in STATUSES}
    return {"overall": counts(sent), "by": by, "status_counts": status_counts,
            "open": sum(r.get("status") not in FINAL for r in rows),
            "median_days_to_reply": statistics.median(waits) if waits else None}


def timeline(events, ident):
    return [e for e in events if e.get("id") == ident]
