"""Learn from your own choices on the dashboard.

The dashboard's "Copy sync lines" button copies lines like

    sync-status: <job-key>=<applied|ready_to_apply_manually|not_applied>
    sync-delete: <job-key>=<the reason you typed, may be empty>

Paste them to Claude Code (CLAUDE.md tells it what to do), or run

    python radar.py sync <file-with-the-lines>      (or pipe them on stdin)

which sets `apply_status` on the matching seen_jobs.json entries, adds an `applied` row to
data/applications.csv for every `applied` line, records a deletion as not interested with
your reason, and rebuilds data/preferences.json: your most recent liked and rejected roles,
which the ranking agents get as calibration examples.
"""
import csv
import datetime
import json
import os
import re
import sys

from . import config
from .collect import load_seen, save_seen

TRACKER_HEADER = ["date", "company", "role", "status", "source", "notes"]
STATUSES = ("applied", "ready_to_apply_manually", "not_applied")
LINE = re.compile(r"^\s*sync-(status|delete):\s*(.+?)=(.*)$")
MAX_EXAMPLES = 15


def _norm(s):
    return re.sub(r"[^a-z0-9äöüß]+", " ", (s or "").lower()).strip()


def parse(text):
    out = []
    for raw in (text or "").splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        kind, key, value = m.group(1), m.group(2).strip(), m.group(3).strip()
        # job keys are URLs and may themselves contain "="; a status value never does
        if kind == "status" and value not in STATUSES:
            key, _, value = raw.split(":", 1)[1].strip().rpartition("=")
        out.append((kind, key, value))
    return out


def upsert_tracker(v, today):
    path = config.data(config.TRACKER)
    rows, header = [], TRACKER_HEADER
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            header = r.fieldnames or TRACKER_HEADER
            rows = list(r)
    target = (_norm(v.get("company")), _norm(v.get("title")))
    for row in rows:
        if (_norm(row.get("company")), _norm(row.get("role"))) == target:
            if row.get("status") == "applied":
                return "already in applications.csv"
            row["status"] = "applied"
            break
    else:
        rows.append({**{h: "" for h in header}, "date": today, "company": v.get("company", ""), "role": v.get("title", ""),
                     "status": "applied", "source": v.get("url", ""), "notes": "from dashboard sync"})
    os.makedirs(config.data_dir(), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return "added to applications.csv"


def build_prefs(seen):
    liked, disliked = [], []
    for v in seen.values():
        when = v.get("user_feedback_date") or v.get("rank_date") or v.get("first_seen") or ""
        label = f"{v.get('title', '')} @ {v.get('company', '')}"
        if v.get("apply_status") in ("applied", "ready_to_apply_manually"):
            liked.append((when, label))
        if v.get("user_feedback") == "not_interested":
            reason = v.get("user_feedback_reason")
            disliked.append((when, label + (f" - reason: {reason}" if reason else "")))
    path = config.data(config.TRACKER)
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("status") and row["status"] not in ("withdrawn", "not_applied"):
                    liked.append((row.get("date") or "", f"{row.get('role', '')} @ {row.get('company', '')}"))
    dedupe = lambda items: list(dict.fromkeys(label for _, label in sorted(items, reverse=True)))[:MAX_EXAMPLES]
    prefs = {"updated": datetime.date.today().isoformat(), "liked": dedupe(liked), "not_interested": dedupe(disliked)}
    os.makedirs(config.data_dir(), exist_ok=True)
    with open(config.data(config.PREFS), "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    return prefs


def apply(text):
    data = load_seen()
    seen = data["seen"]
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
        v = seen.get(key)
        if v is None:
            report.append(f"NOT FOUND {kind}: {key}")
            continue
        if kind == "status":
            old = v.get("apply_status", "not_applied")
            v["apply_status"] = value
            extra = upsert_tracker(v, today) if value == "applied" else ""
            report.append(f"{v.get('title')} @ {v.get('company')}: {old} -> {value} {extra}".rstrip())
        else:
            v.update(user_feedback="not_interested", user_feedback_reason=value, user_feedback_date=today)
            report.append(f"{v.get('title')} @ {v.get('company')}: deleted ({value or 'no reason'})")
    save_seen(data)
    prefs = build_prefs(seen)
    return report, prefs


def cli(args):
    if args.file and args.file != "-":
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    report, prefs = apply(text)
    print("\n".join(report) or "no sync lines found")
    print(f"preferences: {len(prefs['liked'])} liked, {len(prefs['not_interested'])} not interested")
    from . import dashboard
    dashboard.build()
