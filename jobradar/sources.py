"""Collectors for the daily job search (jobradar/collect.py).

Each collector returns a list of postings in one shape:

    {"source": str, "title": str, "company": str, "location": str, "url": str,
     "posted_date": "YYYY-MM-DD" | None, "text": str | None, "text_is_snippet": bool}

`text` is the full posting description where the source provides it (Arbeitnow,
Workable, Bundesagentur), a short listing snippet for englishjobs.de, and None for
LinkedIn (jobradar/prescreen.py fetches LinkedIn detail through the bundled CLI).

Collectors take a `wanted(title, company, location)` callback and skip anything it
rejects before any per-posting detail request, so known and out-of-scope postings
cost no extra traffic. Every collector is polite on purpose: fixed delays, backoff on
HTTP 429, and a hard stop after repeated rate-limiting rather than retrying forever.
Only public endpoints are used; englishjobs.de's /clickout/ redirect links (disallowed
by its robots.txt) are stored for you to click but never fetched here.
"""
import base64
import datetime
import html
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; job-radar personal job search)"


class RateLimited(RuntimeError):
    pass


def http_get(url, headers=None, tries=3, timeout=30):
    """GET with backoff on 429. Raises RateLimited after `tries` consecutive 429s."""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        try:
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            wait = min(int(e.headers.get("Retry-After") or 20 * (attempt + 1)), 90)
            time.sleep(wait)
    raise RateLimited(url)


def http_json(url, headers=None, **kw):
    return json.loads(http_get(url, headers, **kw))


def strip_html(s):
    s = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", s or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def posting(source, title, company, location, url, posted_date, text, snippet=False):
    return {"source": source, "title": (title or "").strip(), "company": (company or "").strip(),
            "location": (location or "").strip(), "url": url, "posted_date": posted_date,
            "text": text, "text_is_snippet": snippet}


# ---------------------------------------------------------------- Arbeitnow
ARBEITNOW_SITES = {"ch": "Switzerland", "co.uk": "United Kingdom", "at": "Austria", "nl": "Netherlands",
                   "fr": "France", "es": "Spain", "it": "Italy", "ie": "Ireland"}


def arbeitnow(since: datetime.date, wanted, delay=3.0, max_pages=40, log=print):
    """Pull the public feed newest-first until postings are older than `since`.
    The API has no keyword parameter, so filtering happens through `wanted`."""
    cut = datetime.datetime.combine(since, datetime.time()).timestamp()
    out = []
    for page in range(1, max_pages + 1):
        data = http_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")["data"]
        if not data:
            break
        for j in data:
            if j["created_at"] < cut:
                continue
            loc = j.get("location") or ("Remote" if j.get("remote") else "")
            # the feed mixes in its country sites; their small towns are unknown to the city lists
            site = ARBEITNOW_SITES.get(urllib.parse.urlsplit(j.get("url") or "").netloc.split("arbeitnow.")[-1])
            if site and site.lower() not in loc.lower():
                loc = f"{loc}, {site}" if loc else site
            if not wanted(j["title"], j["company_name"], loc):
                continue
            out.append(posting("arbeitnow", j["title"], j["company_name"], loc, j["url"],
                               datetime.date.fromtimestamp(j["created_at"]).isoformat(), strip_html(j.get("description"))))
        # The feed is only roughly newest-first (page 1 can span three days and page 5 be
        # newer than page 1's oldest), so stop only once a whole page is older than the
        # window, not at the first old posting.
        if max(j["created_at"] for j in data) < cut:
            break
        time.sleep(delay)
    log(f"arbeitnow: {len(out)} wanted postings ({page} pages)")
    return out


# ---------------------------------------------------------------- Workable
def workable(since: datetime.date, keywords, cities, country_names, wanted, delay=1.0, log=print):
    """Workable's public job search. A country-wide `location` returns nothing for many
    queries, so it searches by city and keeps only postings in `country_names`."""
    cut = since.isoformat()
    seen_ids, out, limited = set(), [], 0
    for kw in keywords:
        for city in cities:
            token = None
            for _ in range(3):
                q = {"query": kw, "location": city}
                if token:
                    q["pageToken"] = token
                try:
                    d = http_json("https://jobs.workable.com/api/v1/jobs?" + urllib.parse.urlencode(q))
                except RateLimited:
                    limited += 1
                    if limited >= 3:
                        log(f"workable: stopped after repeated rate limiting ({len(out)} postings so far)")
                        return out
                    time.sleep(60)
                    break
                fresh = 0
                for j in d.get("jobs", []):
                    if j["id"] in seen_ids:
                        continue
                    seen_ids.add(j["id"])
                    if (j.get("created") or "")[:10] < cut:
                        continue
                    fresh += 1
                    lo = j.get("location") or {}
                    if (lo.get("countryName") or "") not in country_names:
                        continue
                    company = (j.get("company") or {}).get("title")
                    loc = ", ".join(x for x in (lo.get("city"), lo.get("countryName")) if x)
                    if not wanted(j["title"], company, loc):
                        continue
                    text = "\n".join(strip_html(j.get(k)) for k in ("description", "requirementsSection", "benefitsSection"))
                    out.append(posting("workable", j["title"], company, loc, j["url"], j["created"][:10], text))
                token = d.get("nextPageToken")
                if not token or fresh == 0:
                    break
                time.sleep(delay)
            time.sleep(delay)
    log(f"workable: {len(out)} wanted postings")
    return out


# ---------------------------------------------------------------- Bundesagentur für Arbeit
BA_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
BA_KEY = {"X-API-Key": "jobboerse-jobsuche"}  # public client id documented by bundesAPI/jobsuche-api


def bundesagentur(days: int, keywords, wanted, delay=0.3, log=print):
    """Search list (v6) per keyword for regular jobs (angebotsart 1) and internships /
    trainee posts (34), then fetch full text (v4 jobdetails) only for wanted titles."""
    hits = {}
    for kw in keywords:
        for art in (1, 34):
            for page in (1, 2, 3):
                q = urllib.parse.urlencode({"was": kw, "size": 100, "page": page, "veroeffentlichtseit": days, "angebotsart": art})
                lst = http_json(f"{BA_BASE}/pc/v6/jobs?{q}", BA_KEY).get("ergebnisliste") or []
                for j in lst:
                    hits.setdefault(j["referenznummer"], j)
                if len(lst) < 100:
                    break
                time.sleep(delay)
            time.sleep(delay)
    out = []
    for ref, j in hits.items():
        title = j.get("stellenangebotsTitel") or ""
        adr = (j.get("stellenlokationen") or [{}])[0].get("adresse", {})
        loc = adr.get("ort") or ""
        if adr.get("land") and adr["land"] != "DEUTSCHLAND":
            continue
        if not wanted(title, j.get("firma"), loc or "Germany"):
            continue
        b64 = base64.b64encode(ref.encode()).decode()
        try:
            det = http_json(f"{BA_BASE}/pc/v4/jobdetails/{b64}", BA_KEY)
        except (urllib.error.HTTPError, RateLimited) as e:
            log(f"  bundesagentur detail failed for {ref}: {e}")
            continue
        url = det.get("externeUrl") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"
        out.append(posting("bundesagentur", title, j.get("firma"), loc, url, j.get("datumErsteVeroeffentlichung"),
                           det.get("stellenangebotsBeschreibung") or ""))
        time.sleep(delay)
    log(f"bundesagentur: {len(hits)} listings, {len(out)} wanted postings with full text")
    return out


# ---------------------------------------------------------------- englishjobs.de
# The snippet may start with a company logo image (englishjobs.pl does this); it is skipped.
EJ_ITEM = re.compile(r"\[### (.+?)\]\((/clickout/[^)]*)\)\s*\n\s*\n((?:\* .*\n)+)\s*\n?(?:!\[[^\]]*\]\([^)]*\)\s*)?([^\n]*)")


def _ej_date(s, today):
    try:
        d = datetime.datetime.strptime(f"{s} {today.year}", "%B %d %Y").date()
    except ValueError:
        return None
    return d if d <= today else d.replace(year=today.year - 1)


def englishjobs(since: datetime.date, keywords, wanted, delay=2.0, max_pages=10, today=None, log=print,
                domains=("englishjobs.de",)):
    """Nationwide keyword search, newest first, through the site's own markdown view, on each
    country site in `domains` (englishjobs.de, englishjobs.pl). Gives title / company /
    location / date and a one-paragraph snippet only."""
    today = today or datetime.date.today()
    out, seen = [], set()
    for domain, kw in [(dom, k) for dom in domains for k in keywords]:
        slug = urllib.parse.quote(kw.replace(" ", "-"))
        for page in range(1, max_pages + 1):
            md = http_get(f"https://{domain}/jobs/{slug}?format=markdown&sort=date&page={page}").decode("utf-8", "replace")
            items = EJ_ITEM.findall(md)
            if not items:
                break
            oldest = today
            for title, link, meta, snippet in items:
                fields = [x[2:].strip() for x in meta.strip().split("\n")]
                company, loc, date = (fields + ["", "", ""])[:3]
                d = _ej_date(date, today) or today
                oldest = min(oldest, d)
                title = re.sub(r"\*", "", title).strip()
                key = (company.lower(), title.lower())
                if d < since or key in seen:
                    continue
                seen.add(key)
                if not wanted(title, company, loc):
                    continue
                out.append(posting("englishjobs", title, company, loc, f"https://{domain}" + link, d.isoformat(),
                                   re.sub(r"\*", "", snippet).strip(), snippet=True))
            time.sleep(delay)
            if oldest < since:
                break
    log(f"englishjobs: {len(out)} wanted postings")
    return out


# ---------------------------------------------------------------- LinkedIn (through the bundled CLI)
LINKEDIN_CLI = "vendor/linkedin-search/src/cli.ts"
INTERN_TERM = re.compile(r"intern|internship|praktik", re.I)


def linkedin_plan(cfg, day_of_year):
    """{term: look-back days} for today: every daily term, plus the half of the rotating
    terms whose turn it is. A rotating term runs every other day, so it looks back two days
    (with a one-day window it would never see postings from the days it skips)."""
    plan = {t: cfg.get("jobage_days", 1) for t in cfg.get("daily_terms", [])}
    rotating = cfg.get("rotating_terms", [])
    half = rotating[day_of_year % 2::2]
    plan.update({t: cfg.get("rotate_jobage_days", 2) for t in half if t not in plan})
    return plan


def linkedin(cfg, wanted, root, day_of_year=None, log=print, run=subprocess.run):
    """Today's LinkedIn terms (see linkedin_plan) through vendor/linkedin-search, country-wide
    first; the city top-up runs only for terms whose country-wide search hit the page cap.
    `cfg` is the profile's [search.linkedin] table."""
    day_of_year = day_of_year or datetime.date.today().timetuple().tm_yday
    plan = linkedin_plan(cfg, day_of_year)
    delay, cap = cfg.get("delay_seconds", 1.5), cfg.get("max_pages", 5)
    areas = cfg.get("locations") or [{"base": cfg.get("location", "Germany"), "city_topup": cfg.get("city_topup", [])}]

    def search(term, loc, page, jobage):
        cmd = ["bun", "run", LINKEDIN_CLI, "search", "-q", term, "-l", loc,
               "--jobage", str(jobage), "--page", str(page), "--format", "json"]
        r = run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8")
        time.sleep(delay)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout).get("results", [])

    out, seen_ids, failures, calls = [], set(), 0, 0

    def take(results):
        for j in results:
            if j["id"] in seen_ids:
                continue
            seen_ids.add(j["id"])
            if wanted(j["title"], j["company"], j["location"]):
                out.append(posting("linkedin-search", j["title"], j["company"], j["location"],
                                   j["url"].split("?")[0], j.get("date"), None))

    for area in areas:
        for term, jobage in plan.items():
            if area.get("full_time_only") and INTERN_TERM.search(term):
                continue
            truncated = False
            for page in range(1, cap + 1):
                res = search(term, area["base"], page, jobage); calls += 1
                if res is None:
                    failures += 1
                    break
                take(res)
                if len(res) < 10:
                    break
                truncated = page == cap
            if truncated:
                for city in area.get("city_topup", []):
                    res = search(term, city, 1, jobage); calls += 1
                    if res is None:
                        failures += 1
                        continue
                    take(res)
            if failures >= 5:
                log(f"linkedin: stopped after {failures} failed calls ({calls} calls, {len(out)} postings so far)")
                return out
    log(f"linkedin: {len(plan)} terms, {calls} calls, {len(out)} wanted postings")
    return out
