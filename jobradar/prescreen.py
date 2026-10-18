"""Deterministic pre-screen, run at the end of every collection (no LLM).

For every seen_jobs.json entry with status "new" that has not been pre-screened, read the
posting's full text (its data/jd_cache file, or LinkedIn's detail page through the bundled
CLI) and skip what the ranking would exclude anyway:

  - a senior title (if your profile skips them), another track, a gig-work title, or a
    title outside your directions                                -> "skipped"
  - a location outside your countries, or an internship outside your internship countries
  - an explicit requirement of rules.skip_if_years_at_least years or more
  - LinkedIn reports the posting as closed                         -> "expired"
  - graduates and experienced profiles only: an internship that requires current
    enrollment, names a mandatory internship / working-student role, or belongs to a
    company you listed as enrolled-only. An internship that simply does not say whether
    graduates can apply is kept and flagged.
  - a posting written in Dutch or Polish when you do not speak that language at B2+
  - outside your work-permit countries: a posting that requires a local work permit or
    says it does not sponsor visas
  - German below C1 only: a posting that demands fluent German, and German-written
    postings according to rules.german_jd_policy

Ambiguous cases ("(Senior)" in parentheses, "2-3 years", "first experience") stay "new" for
the ranking to judge. An entry with only a listing snippet (englishjobs) gets the title and
location rules here and is judged later from the employer's own posting.
"""
import datetime
import json
import os
import subprocess
import time

from . import config
from .jd_language import detect
from .rules import (INTERN_HARD_BLOCK, INTERNSHIP_TITLE, SOFT_GERMAN, WORK_PERMIT_REQUIRED, enrolled_only_company,
                    enrollment_required, german_required, internship_unconfirmed, senior_skip, title_rejection,
                    years_requirement)

LANG_NAMES = {"nl": "dutch", "pl": "polish"}


def read_cached_text(entry):
    name = entry.get("jd_cache")
    if not name:
        return None
    path = config.data(config.JD_CACHE, os.path.basename(name))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def cli_detail(entry):
    """LinkedIn detail through vendor/linkedin-search (needs bun), or None."""
    if entry.get("portal") != "linkedin-search":
        return None
    import re
    m = re.search(r"(\d{8,})", entry.get("url") or "")
    if not m:
        return None
    cmd = ["bun", "run", "vendor/linkedin-search/src/cli.ts", "detail", m.group(1), "--format", "json"]
    try:
        r = subprocess.run(cmd, cwd=config.ROOT, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def cache_detail(key, entry, detail):
    from .collect import cache_name
    name = cache_name(key)
    os.makedirs(config.data(config.JD_CACHE), exist_ok=True)
    with open(config.data(config.JD_CACHE, name), "w", encoding="utf-8") as f:
        f.write(detail["description"])
    entry["jd_cache"] = name
    if detail.get("employmentType"):
        entry["employment_type"] = detail["employmentType"]


def skip(v, stats, counter, reason, **fields):
    v.update(status="skipped", skip_reason=f"prescreen: {reason}", **fields)
    stats[counter] = stats.get(counter, 0) + 1


def screen(key, v, profile, today, stats):
    """Pre-screen one entry in place."""
    title = v.get("title", "")
    v["prescreen_date"] = today
    if senior_skip(title, profile):
        return skip(v, stats, "skipped_senior_title", "senior title", experience_gate="FAIL_CLEAR",
                    experience_note=f"senior title '{title}'")
    reason = title_rejection(title, profile)
    if reason:
        return skip(v, stats, "skipped_title_rule", reason)
    country = profile.country_of(v.get("location", ""), strict=(v.get("portal") or "").startswith("ats:"))
    if country is None:
        return skip(v, stats, "skipped_location", "outside your countries")
    v["country"] = country
    if INTERNSHIP_TITLE.search(title) and country not in profile.internship_countries:
        return skip(v, stats, "skipped_location", "internship outside your internship countries", internship_gate="FAIL")

    text = read_cached_text(v)
    if text is not None and v.get("jd_snippet_only"):
        stats["snippet_only"] = stats.get("snippet_only", 0) + 1
        return
    detail = {"description": text} if text is not None else cli_detail(v)
    if detail is None or not detail.get("description"):
        stats["no_detail"] = stats.get("no_detail", 0) + 1
        return
    if text is None:
        cache_detail(key, v, detail)
        time.sleep(1)
    desc = detail["description"]
    lang = detect(desc)
    v.update(posting_language=lang["lang"], english_working_language=lang["english_ok"])
    stats[f"lang_{lang['lang'] if lang['lang'] in ('en', 'de') else 'other'}"] = \
        stats.get(f"lang_{lang['lang'] if lang['lang'] in ('en', 'de') else 'other'}", 0) + 1
    if detail.get("isActive") is False:
        v["status"] = "expired"
        stats["expired"] = stats.get("expired", 0) + 1
        return

    yrs, ev = years_requirement(desc)
    if yrs is not None and yrs >= profile.skip_years:
        return skip(v, stats, "skipped_years", "multi-year requirement", experience_gate="FAIL_CLEAR",
                    experience_note=f"requires {yrs}+ years ('{ev}')")

    employment = detail.get("employmentType") or v.get("employment_type") or ""
    is_intern = bool(INTERNSHIP_TITLE.search(title)) or employment.lower() == "internship"
    if is_intern and country not in profile.internship_countries:
        return skip(v, stats, "skipped_location", "internship outside your internship countries", internship_gate="FAIL")
    if is_intern and profile.stage != "student":
        enrol = enrollment_required(title, desc)
        if enrol:
            return skip(v, stats, "skipped_enrollment", "internship requires enrollment", internship_gate="FAIL",
                        internship_note=f"requires current enrollment ('{enrol}')")
        if enrolled_only_company(v.get("company", ""), profile):
            return skip(v, stats, "skipped_enrollment", "company internships are for enrolled students",
                        internship_gate="FAIL", internship_note="this company's internships are for enrolled students only")
        blocked = INTERN_HARD_BLOCK.search(f"{title}\n{desc}")
        if blocked:
            return skip(v, stats, "skipped_enrollment", "mandatory internship / working student wording",
                        internship_gate="FAIL", internship_note=f"'{blocked.group(0)}' in posting")
        if internship_unconfirmed(title, desc, employment):
            v.update(internship_gate="UNCONFIRMED", internship_note="the posting does not say whether graduates can apply")
            stats["kept_intern_unconfirmed"] = stats.get("kept_intern_unconfirmed", 0) + 1

    if lang["lang"] in LANG_NAMES and not lang["english_ok"] and not profile.speaks(LANG_NAMES[lang["lang"]]):
        name = LANG_NAMES[lang["lang"]].capitalize()
        return skip(v, stats, "skipped_language", f"{name}-written posting", language_gate="FAIL",
                    language_note=f"posting written in {name}")
    if country not in profile.work_permit_countries:
        permit = WORK_PERMIT_REQUIRED.search(desc)
        if permit:
            return skip(v, stats, "skipped_work_permit", "local work permit required", work_auth_gate="FAIL",
                        work_auth_note=f"'{permit.group(0).strip()[:80]}'")

    if not profile.german_gate:
        return
    req = german_required(desc)
    if lang["lang"] == "de" and not lang["english_ok"]:
        policy = profile.german_jd_policy
        if req or policy == "skip":
            return skip(v, stats, "skipped_language", "German-written posting", language_gate="FAIL",
                        language_note=f"German posting{' requiring fluent German' if req else ''}"
                                      + (f" ('{req}')" if req else ""))
        if policy == "soft-only":
            soft = SOFT_GERMAN.search(desc)
            if not soft:
                # a German posting that states no German level is a German-speaking job in practice
                return skip(v, stats, "skipped_language", "German-written posting without a soft German statement",
                            language_gate="FAIL", language_note="German posting with no stated German level")
            v.update(language_flag="DE_JD",
                     language_note=f"posting written in German; asks only soft German ('{soft.group(0).strip()[:60]}')")
            stats["kept_soft_german"] = stats.get("kept_soft_german", 0) + 1
        return
    if req:
        return skip(v, stats, "skipped_language", "fluent German required", language_gate="FAIL",
                    language_note=f"German required ('{req}')")


def run(data, profile, limit=0):
    """Pre-screen every new, unscreened entry of `data` in place; returns the counters."""
    today = datetime.date.today().isoformat()
    todo = [(k, v) for k, v in data["seen"].items() if v.get("status") == "new" and not v.get("prescreen_date")]
    if limit:
        todo = todo[:limit]
    stats = {"checked": 0}
    for key, v in todo:
        stats["checked"] += 1
        screen(key, v, profile, today, stats)
    return stats


def cli(args):
    from .collect import load_seen, lock_holder_alive, save_seen
    if lock_holder_alive():
        raise SystemExit("a collection is running and will pre-screen when it finishes")
    data = load_seen()
    stats = run(data, config.get(), limit=args.limit)
    if not args.dry_run:
        save_seen(data)
    print(json.dumps(stats))
