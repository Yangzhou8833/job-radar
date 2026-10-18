"""Learn from your own choices on the dashboard.

With `python radar.py serve` the dashboard saves every click directly. Opened as a plain
file, it cannot write to disk, so its "Copy sync lines" button copies lines like

    sync-status: <job-key>=<applied|ready_to_apply_manually|not_applied>
    sync-delete: <job-key>=<the reason you typed, may be empty>
    sync-app: <application-id>=<drafted|applied|interview|offer|hired|rejected|no_response|offer_declined|withdrawn>

Paste them to Claude Code (CLAUDE.md tells it what to do), or run

    python radar.py sync <file-with-the-lines>      (or pipe them on stdin)

A job marked `applied` becomes an application in data/applications.csv (see
jobradar/applications.py); a deleted job is recorded as not interested with your reason; an
application line moves that application and adds it to its timeline. Then
data/preferences.json is rebuilt: roles that led to interviews, roles you applied to, and
roles you rejected with reasons. The ranking agents get it as calibration examples, with
interviews as the strongest signal.
"""
import datetime
import json
import os
import re
import sys

from . import applications, config
from .collect import load_seen, save_seen

JOB_STATUSES = ("applied", "ready_to_apply_manually", "not_applied")
LINE = re.compile(r"^\s*sync-(status|delete|app):\s*(.+?)=(.*)$")
MAX_EXAMPLES = 15


def parse(text):
    out = []
    for raw in (text or "").splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        kind, key, value = m.group(1), m.group(2).strip(), m.group(3).strip()
        # job keys are URLs and may themselves contain "="; a status value never does
        if kind in ("status", "app") and "=" in value:
            key, _, value = raw.split(":", 1)[1].strip().rpartition("=")
        out.append((kind, key, value))
    return out


def build_prefs(seen, rows=None, events=None):
    rows = applications.load() if rows is None else rows
    events = applications.load_events() if events is None else events
    interviews, liked, disliked = [], [], []
    for v in seen.values():
        when = v.get("user_feedback_date") or v.get("rank_date") or v.get("first_seen") or ""
        label = f"{v.get('title', '')} @ {v.get('company', '')}"
        if v.get("apply_status") in ("applied", "ready_to_apply_manually"):
            liked.append((when, label))
        if v.get("user_feedback") == "not_interested":
            reason = v.get("user_feedback_reason")
            disliked.append((when, label + (f" - reason: {reason}" if reason else "")))
    for r in rows:
        label = f"{r.get('role', '')} @ {r.get('company', '')}"
        when = r.get("updated") or r.get("date") or ""
        if applications.reached(r, events) >= 2:
            interviews.append((when, label))
        elif r.get("status") not in ("withdrawn", "drafted"):
            liked.append((when, label))
    dedupe = lambda items: list(dict.fromkeys(label for _, label in sorted(items, reverse=True)))[:MAX_EXAMPLES]
    got = dedupe(interviews)
    prefs = {"updated": datetime.date.today().isoformat(), "interviews": got,
             "liked": [x for x in dedupe(liked) if x not in got], "not_interested": dedupe(disliked)}
    os.makedirs(config.data_dir(), exist_ok=True)
    with open(config.data(config.PREFS), "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    return prefs


def mark_job(seen, rows, key, status, today):
    """One job's dashboard status; `applied` also creates or advances its application."""
    v = seen.get(key)
    if v is None:
        return f"NOT FOUND job: {key}"
    if status not in JOB_STATUSES:
        return f"SKIPPED {key}: unknown job status {status!r}"
    old = v.get("apply_status", "not_applied")
    v["apply_status"] = status
    extra = ""
    if status == "applied":
        _, extra = applications.upsert_from_job(rows, key, v, "applied", when=today)
        extra = f"(application {extra})"
    return f"{v.get('title')} @ {v.get('company')}: {old} -> {status} {extra}".rstrip()


def delete_job(seen, key, reason, today):
    v = seen.get(key)
    if v is None:
        return f"NOT FOUND job: {key}"
    v.update(user_feedback="not_interested", user_feedback_reason=reason, user_feedback_date=today)
    return f"{v.get('title')} @ {v.get('company')}: deleted ({reason or 'no reason'})"


def apply(text):
    data = load_seen()
    seen = data["seen"]
    rows = applications.load()
    today = datetime.date.today().isoformat()
    report = []
    for kind, key, value in parse(text):
        if kind == "delete" and key not in seen:
            # a key with "=" in it (URL query) was split too early; find the split that names a job
            rest = f"{key}={value}"
            for i in [m.start() for m in re.finditer("=", rest)][::-1]:
                if rest[:i] in seen:
                    key, value = rest[:i], rest[i + 1:]
                    break
        if kind == "status":
            report.append(mark_job(seen, rows, key, value, today))
        elif kind == "delete":
            report.append(delete_job(seen, key, value, today))
        else:
            try:
                row = applications.set_status(rows, key, value, when=today)
                report.append(f"{row.get('role')} @ {row.get('company')}: application -> {row['status']}")
            except (KeyError, ValueError) as e:
                report.append(f"SKIPPED application {key}: {e}")
    save_seen(data)
    applications.save(rows)
    prefs = build_prefs(seen, rows)
    return report, prefs


def cli(args):
    if args.file and args.file != "-":
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    report, prefs = apply(text)
    print("\n".join(report) or "no sync lines found")
    print(f"preferences: {len(prefs['interviews'])} interviews, {len(prefs['liked'])} applied, "
          f"{len(prefs['not_interested'])} not interested")
    from . import dashboard
    dashboard.build()
