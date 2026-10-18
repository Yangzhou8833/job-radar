"""Stage A of the daily run: collect, deduplicate, gate by title, store, pre-screen.

Collects new postings from every source in your profile, keeps the ones worth a closer
look, writes them to data/seen_jobs.json with status "new", and runs the deterministic
pre-screen (jobradar/prescreen.py). Costs no LLM tokens; the ranking (stage B, the
/daily-rank command in Claude Code) takes it from there.

    python radar.py collect                    # all sources, postings from the last N days (profile)
    python radar.py collect --sources arbeitnow,englishjobs --days 3
    python radar.py collect --dry-run          # collect and report, write nothing

What a posting must pass before it is stored (counted per reason in the run log):
  - a location in one of your countries (internships only in your internship countries)
  - not already known: same URL, or same normalized company + title, in seen_jobs.json,
    data/applications.csv, or earlier in this run
  - a title that is not senior (if you skip senior titles), not another track (Werkstudent,
    Ausbildung, thesis...), not a mandatory or unpaid internship, not warehouse / gig work,
    and that matches one of your direction groups

Rejected titles are not stored (Arbeitnow alone lists thousands of postings a week); the
run log under data/runs/ keeps the counts. A lock file stops two runs from writing
seen_jobs.json at the same time.
"""
import csv
import datetime
import glob
import hashlib
import json
import os
import re
import sys
import time
import traceback

from . import ats_feeds, config, countries, prescreen, sources
from .rules import INTERNSHIP_TITLE, norm_key, senior_skip, title_rejection

LOCK_STALE_HOURS = 3
# Sources that deliver full text run first, so when the same job appears on several boards
# the stored copy is the one the pre-screen can actually read.
SOURCE_ORDER = ["bundesagentur", "arbeitnow", "ats", "workable", "linkedin", "englishjobs"]


# ---------------------------------------------------------------- lock
def pid_alive(pid):
    """Whether a process with this id is still running (Windows and POSIX)."""
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def lock_holder_alive():
    lock = config.data(config.LOCK)
    if not os.path.exists(lock):
        return False
    m = re.search(r"pid=(\d+)", open(lock, encoding="utf-8").read())
    age_h = (time.time() - os.path.getmtime(lock)) / 3600
    return bool(m and pid_alive(int(m.group(1))) and age_h < LOCK_STALE_HOURS)


def acquire_lock():
    lock = config.data(config.LOCK)
    if lock_holder_alive():
        holder = open(lock, encoding="utf-8").read().strip()
        raise SystemExit(f"seen_jobs.json is locked by another run ({holder}). "
                         f"Wait for it to finish, or delete {lock} if no run is active.")
    # a run killed mid-way (PC asleep, window closed) leaves its lock behind; it is taken over
    with open(lock, "w", encoding="utf-8") as f:
        f.write(f"collect pid={os.getpid()} started={datetime.datetime.now().isoformat(timespec='seconds')}")


def release_lock():
    lock = config.data(config.LOCK)
    if os.path.exists(lock):
        os.remove(lock)


def todays_finished_run(wanted_sources):
    """Path of today's completed (non-dry) full run log, or None."""
    day = datetime.date.today().isoformat()
    for path in sorted(glob.glob(config.data(config.RUNS, f"{day}_*.json")), reverse=True):
        if path.endswith("_dry.json"):
            continue
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
        if r.get("finished") and set(wanted_sources) <= set(r.get("sources", {})):
            return path
    return None


def ensure_today_done(wanted_sources, max_wait_hours=5):
    """True when today's full collection has finished (possibly after waiting for one that
    is still running). False means nothing ran today, so the caller runs it now. Used when
    collection is scheduled outside Claude and the ranking runs later."""
    if todays_finished_run(wanted_sources):
        print("today's collection already finished")
        return True
    deadline = time.time() + max_wait_hours * 3600
    while lock_holder_alive() and time.time() < deadline:
        print("a collection is still running; waiting...", flush=True)
        time.sleep(300)
    if todays_finished_run(wanted_sources):
        print("today's collection finished")
        return True
    print("no finished collection today; running one now", flush=True)
    return False


# ---------------------------------------------------------------- known postings
def load_known(seen):
    urls, keys = set(), set()
    for k, v in seen.items():
        urls.add(k)
        if v.get("url"):
            urls.add(v["url"])
        keys.add(norm_key(v.get("company"), v.get("title")))
    counts = {"seen_jobs": len(seen), "applications": 0}
    tracker = config.data(config.TRACKER)
    if os.path.exists(tracker):
        with open(tracker, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                keys.add(norm_key(row.get("company"), row.get("role")))
                if row.get("source"):
                    urls.add(row["source"])
                counts["applications"] += 1
    return urls, keys, counts


class Gate:
    """The `wanted(title, company, location)` callback handed to every collector, with
    per-reason counters."""

    def __init__(self, urls, keys, profile):
        self.urls, self.keys, self.profile = urls, keys, profile
        self.counts = {}

    def _drop(self, reason):
        self.counts[reason] = self.counts.get(reason, 0) + 1
        return False

    def __call__(self, title, company, location):
        p = self.profile
        country = p.country_of(location)
        if country is None:
            return self._drop("outside your countries")
        if INTERNSHIP_TITLE.search(title or "") and country not in p.internship_countries:
            return self._drop("internship outside your internship countries")
        key = norm_key(company, title)
        if key in self.keys:
            return self._drop("already known (seen_jobs / applications / this run)")
        if senior_skip(title, p):
            return self._drop("senior title")
        reason = title_rejection(title, p)
        if reason:
            return self._drop(reason)
        self.keys.add(key)  # first source to deliver a job wins; later copies count as known
        self.counts["passed"] = self.counts.get("passed", 0) + 1
        return True


# ---------------------------------------------------------------- run
def collect_source(name, profile, since, gate, log):
    s = profile.search
    keywords = s.get("keywords", [])
    if name == "arbeitnow":
        return sources.arbeitnow(since, gate, log=log)
    if name == "workable":
        names = {countries.workable_name(c) for c in profile.countries}
        return sources.workable(since, s.get("workable_keywords", keywords), s.get("workable_cities", []), names,
                                gate, log=log)
    if name == "bundesagentur":
        if "DE" not in profile.countries:
            log("bundesagentur: skipped (Germany is not in your countries)")
            return []
        days = max(1, (datetime.date.today() - since).days)
        return sources.bundesagentur(days, keywords, gate, log=log)
    if name == "englishjobs":
        return sources.englishjobs(since, keywords, gate, log=log,
                                   domains=s.get("englishjobs_domains", ["englishjobs.de"]))
    if name == "ats":
        return ats_feeds.collect(gate, log=log)
    if name == "linkedin":
        return sources.linkedin(s.get("linkedin", {}), gate, config.ROOT, log=log)
    raise ValueError(f"unknown source {name!r}")


def cache_name(key):
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".txt"


def store(seen, postings, today, dry_run, known_urls=()):
    added = 0
    for p in postings:
        if p["source"] == "englishjobs":
            # its /clickout/ links carry a per-request signature, so they are not a stable key
            key = "englishjobs:" + norm_key(p["company"], p["title"])
        else:
            key = p["url"]
        if key in seen or p["url"] in seen or p["url"] in known_urls:
            continue
        entry = {"title": p["title"], "company": p["company"], "location": p["location"], "url": p["url"],
                 "first_seen": today, "posted_date": p["posted_date"], "deadline": None,
                 "status": "new", "portal": p["source"]}
        if p.get("text"):
            name = cache_name(key)
            entry["jd_cache"] = name
            if p.get("text_is_snippet"):
                entry["jd_snippet_only"] = True
            if not dry_run:
                with open(config.data(config.JD_CACHE, name), "w", encoding="utf-8") as f:
                    f.write(p["text"])
        seen[key] = entry
        added += 1
    return added


def load_seen():
    path = config.data(config.SEEN)
    if not os.path.exists(path):
        return {"seen": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_seen(data):
    os.makedirs(config.data_dir(), exist_ok=True)
    tmp = config.data(config.SEEN + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, config.data(config.SEEN))


def run(args):
    profile = config.get()
    wanted_sources = [s for s in SOURCE_ORDER if s in (args.sources.split(",") if args.sources
                                                         else profile.search.get("sources", SOURCE_ORDER))]
    if "linkedin" in wanted_sources and not profile.search.get("linkedin", {}).get("enabled"):
        wanted_sources.remove("linkedin")
    if args.ensure_today and ensure_today_done(wanted_sources):
        return

    started = datetime.datetime.now()
    today = started.date().isoformat()
    since = started.date() - datetime.timedelta(days=args.days or profile.search.get("days", 2))
    lines = []
    os.makedirs(config.data(config.JD_CACHE), exist_ok=True)
    os.makedirs(config.data(config.RUNS), exist_ok=True)
    live = config.data(config.RUNS, "latest.log")  # follow progress while a run is going
    open(live, "w", encoding="utf-8").close()

    def log(msg):
        stamped = f"{datetime.datetime.now():%H:%M:%S} {msg}"
        print(stamped, flush=True)
        lines.append(stamped)
        with open(live, "a", encoding="utf-8") as f:
            f.write(stamped + "\n")

    if not args.dry_run:
        acquire_lock()
    try:
        data = load_seen()
        seen = data["seen"]
        urls, keys, known_counts = load_known(seen)
        log(f"known postings: {known_counts}")
        gate = Gate(urls, keys, profile)
        report = {"started": started.isoformat(timespec="seconds"), "since": since.isoformat(), "sources": {}}
        for name in wanted_sources:
            log(f"{name}: starting")
            t0 = time.time()
            try:
                postings = collect_source(name, profile, since, gate, log)
                added = store(seen, postings, today, args.dry_run, urls)
                report["sources"][name] = {"collected": len(postings), "added": added, "seconds": round(time.time() - t0)}
            except Exception as e:  # one broken source must not stop the others
                log(f"{name}: FAILED - {type(e).__name__}: {e}")
                report["sources"][name] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
        report["title_gate"] = gate.counts

        if not args.dry_run and "englishjobs" in wanted_sources:
            # englishjobs gives only a snippet: swap in the employer's own posting where we can find it
            try:
                report["snippets_resolved"] = ats_feeds.resolve_snippets(
                    seen, budget=profile.budget("snippet_resolve", 400), log=log)
            except Exception as e:
                log(f"snippet resolve: FAILED - {type(e).__name__}: {e}")

        if not args.dry_run and "ats" in wanted_sources:
            # grow the company-feed registry for tomorrow: boards linked from anything stored
            # today, then a budgeted round of name-guessing
            try:
                save_seen(data)
                report["ats_harvest"] = ats_feeds.harvest(log=log)
                report["ats_probe"] = ats_feeds.probe(budget=profile.budget("ats_probe", 600), log=log)
            except Exception as e:
                log(f"ats discovery: FAILED - {type(e).__name__}: {e}")

        if not args.dry_run:
            if not args.no_prescreen:
                report["prescreen"] = prescreen.run(data, profile)
                log(f"prescreen: {json.dumps(report['prescreen'])}")
            save_seen(data)
        report["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
        report["log"] = lines
        out = config.data(config.RUNS, started.strftime("%Y-%m-%d_%H%M") + ("_dry" if args.dry_run else "") + ".json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log(f"run log: {config.rel(out)}")
    finally:
        if not args.dry_run:
            release_lock()
