#!/usr/bin/env python3
"""Job Radar command line. Run `python radar.py <command> --help` for details.

Daily pipeline
  collect          stage A: collect from every source, dedupe, gate by title, pre-screen (no LLM)
  rank-prepare     write ranking batches for the job-triage agents
  rank-apply       write the agents' verdicts back and rebuild the dashboard
  verify-prepare   batches of snippet-only high/medium roles for the job-verify agents
  verify-apply     store the verified postings and requeue them for ranking
  serve            open the dashboard with direct saving (local only)
  dashboard        rebuild reports/dashboard.html (static file)
  digest           write (and send, if enabled) today's email
  sync             apply sync lines copied from the dashboard

Setup and maintenance
  cv-extract       turn the CV in profile/ into profile/cv.txt (used by /setup)
  profile-check    show what your profile resolves to, and test job titles against it
  prescreen        re-run the pre-screen on unscreened entries
  ats              company career boards: harvest | probe | list | add
  sources          list built-in and custom sources (sources_custom/) and which ones run
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobradar import ats_feeds, collect, config, cv_extract, dashboard, digest, feedback, prescreen, rank, server  # noqa: E402
from jobradar.rules import senior_skip, title_rejection  # noqa: E402


def profile_check(args):
    p = config.get()
    print(f"profile: {config.rel(p.path)}")
    print(f"candidate: {p.name or '(no name)'}, {p.stage}, {p.years:g} years")
    print(f"countries: {', '.join(p.countries)} | internships: {', '.join(p.internship_countries) or 'none'}"
          f" | no sponsorship needed: {', '.join(p.work_permit_countries)} | unknown location -> {p.unknown_location or 'out of scope'}")
    print(f"languages: {p.language_summary()} | German rules: "
          + (f"on (German-written postings: {p.german_jd_policy})" if p.german_gate else "off (German C1+)"))
    print(f"skip: {p.skip_years}+ years required" + (", senior titles" if p.skip_senior else ""))
    print(f"directions ({len(p.directions)}): {', '.join(p.directions)}")
    s = p.search
    chosen, _ = collect.chosen_sources(p, log=lambda m: print("WARNING:", m))
    print(f"sources: {', '.join(chosen)}" + (f" | company boards listed: {len(s.get('company_boards', []))}"
                                             if s.get("company_boards") else ""))
    print(f"search keywords: {len(s.get('keywords', []))}, digest: {'on' if p.digest.get('enabled') else 'off'}")
    if not p.summary:
        print("WARNING: candidate.summary is empty; the ranking agents will know almost nothing about you")
    for title in args.title or []:
        reason = "senior title" if senior_skip(title, p) else title_rejection(title, p)
        print(f"  {'SKIP' if reason else 'KEEP'}  {title}" + (f"  ({reason})" if reason else f"  -> {', '.join(p.families_of(title))}"))
    if args.prompt:
        print("\n----- ranking prompt -----\n" + rank.agent_prompt(p))


def list_sources(args):
    p = config.get()
    order, custom = collect.available_sources()
    chosen, _ = collect.chosen_sources(p, log=lambda m: print("WARNING:", m), custom=custom)
    for name in order:
        kind = "custom" if name in custom else "built-in"
        text = "full text" if (name not in custom and name in collect.BUILTIN_FULL_TEXT) or             (name in custom and getattr(custom[name], "FULL_TEXT", True)) else "snippet / fetched later"
        print(f"  {'ON ' if name in chosen else 'off'}  {name:<14} {kind:<8} {text}")
    print("Turn sources on or off in [search] sources; add your own in sources_custom/ (or /add-source).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="stage A: collect, dedupe, gate, pre-screen")
    c.add_argument("--sources", help="comma-separated subset, e.g. arbeitnow,englishjobs")
    c.add_argument("--days", type=int, help="keep postings from the last N days (default: profile search.days)")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--no-prescreen", action="store_true")
    c.add_argument("--ensure-today", action="store_true",
                   help="return at once if today's collection finished, wait for a running one, else run it now")
    c.set_defaults(func=collect.run)

    p = sub.add_parser("rank-prepare")
    p.add_argument("--first-seen")
    p.add_argument("--batch-size", type=int, default=25)
    p.set_defaults(func=rank.cmd_prepare)
    a = sub.add_parser("rank-apply")
    a.add_argument("run_dir")
    a.add_argument("--no-dashboard", action="store_true")
    a.set_defaults(func=rank.cmd_apply)
    vp = sub.add_parser("verify-prepare")
    vp.add_argument("--limit", type=int, default=0)
    vp.set_defaults(func=rank.cmd_verify_prepare)
    va = sub.add_parser("verify-apply")
    va.add_argument("run_dir")
    va.set_defaults(func=rank.cmd_verify_apply)

    sub.add_parser("dashboard").set_defaults(func=lambda args: dashboard.build())
    sv = sub.add_parser("serve", help="dashboard with direct saving, on 127.0.0.1 only")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--no-browser", action="store_true")
    sv.set_defaults(func=server.serve)
    d = sub.add_parser("digest")
    d.add_argument("--date")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--force", action="store_true", help="send even if this date's digest was already sent")
    d.set_defaults(func=digest.cli)
    s = sub.add_parser("sync")
    s.add_argument("file", nargs="?", default="-")
    s.set_defaults(func=feedback.cli)

    x = sub.add_parser("cv-extract")
    x.add_argument("path", nargs="?")
    x.set_defaults(func=cv_extract.cli)
    k = sub.add_parser("profile-check")
    k.add_argument("--title", action="append", help="test a job title against your rules (repeatable)")
    k.add_argument("--prompt", action="store_true", help="also print the generated ranking prompt")
    k.set_defaults(func=profile_check)
    ps = sub.add_parser("prescreen")
    ps.add_argument("--dry-run", action="store_true")
    ps.add_argument("--limit", type=int, default=0)
    ps.set_defaults(func=prescreen.cli)

    sub.add_parser("sources").set_defaults(func=list_sources)
    t = sub.add_parser("ats")
    tsub = t.add_subparsers(dest="ats_cmd", required=True)
    tsub.add_parser("harvest")
    tp = tsub.add_parser("probe")
    tp.add_argument("--budget", type=int, default=600)
    tsub.add_parser("list")
    ta = tsub.add_parser("add")
    ta.add_argument("ats", choices=ats_feeds.ATS_NAMES)
    ta.add_argument("board")
    ta.add_argument("company", nargs="?")
    t.set_defaults(func=ats_feeds.cli)

    args = ap.parse_args()
    result = args.func(args)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
