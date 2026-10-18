"""Company career feeds through the public job-board APIs of applicant tracking systems.

Startups and international employers mostly post in English on Personio, Ashby,
Greenhouse, Lever, Recruitee or SmartRecruiters, and many of those roles never reach
LinkedIn or the Bundesagentur. Each of these systems serves a company's complete list of
open roles from one public endpoint, so once a company's board is known, its feed is
pulled every day for free (no LLM).

The registry of known boards (data/ats_registry.json) grows by itself:

  - harvest: any URL seen anywhere (seen_jobs.json entries, cached posting text) that
    points at one of these systems is a board. Free, runs every day.
  - probe:   for companies seen on other boards, guess the board slug from the company
    name and accept it only when the feed holds a role whose normalized title matches a
    role we already saw from that company (so a same-named stranger is never added).
    Runs within a daily request budget and never retries a guess for 30 days.

    python radar.py ats harvest          # add boards found in stored URLs / texts
    python radar.py ats probe --budget 600
    python radar.py ats list
    python radar.py ats add personio westwing "Westwing"   # add a board by hand
"""
import datetime
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, countries
from .sources import RateLimited, http_get, http_json, posting, strip_html

RETRY_DAYS = 30


def _paths():
    return config.data(config.REGISTRY), config.data(config.SEEN), config.data(config.JD_CACHE)

# URL patterns that identify a board. Group 1 is the board slug.
URL_PATTERNS = [
    ("greenhouse", re.compile(r"(?:job-boards(?:\.eu)?|boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_.-]+)", re.I)),
    ("lever_eu", re.compile(r"jobs\.eu\.lever\.co/([a-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.%-]+)", re.I)),
    ("personio", re.compile(r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.I)),
    ("recruitee", re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
]
NOT_A_BOARD = {"embed", "api", "v1", "jobs", "job", "careers", "www", "app", "boards", "oauth", "static"}


def today():
    return datetime.date.today().isoformat()


def load_registry():
    path = _paths()[0]
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"boards": {}, "probed": {}}


def save_registry(reg):
    os.makedirs(config.data_dir(), exist_ok=True)
    with open(_paths()[0], "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)


def board_key(ats, board):
    return f"{ats}:{board.lower()}"


def boards_in_text(text):
    found = set()
    for ats, rx in URL_PATTERNS:
        for m in rx.finditer(text or ""):
            board = urllib.parse.unquote(m.group(1)).strip("/.")
            if board and board.lower() not in NOT_A_BOARD:
                found.add((ats, board))
    return found


# ---------------------------------------------------------------- feeds
def _date(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):  # Lever: epoch milliseconds
        return datetime.date.fromtimestamp(value / 1000).isoformat()
    return str(value)[:10]


def fetch_greenhouse(board, company):
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    out = []
    for j in d.get("jobs", []):
        out.append(posting("ats:greenhouse", j["title"], j.get("company_name") or company,
                           (j.get("location") or {}).get("name", ""), j["absolute_url"],
                           _date(j.get("first_published") or j.get("updated_at")), strip_html(html.unescape(j.get("content") or ""))))
    return out


def fetch_lever(board, company, eu=False):
    host = "api.eu.lever.co" if eu else "api.lever.co"
    d = http_json(f"https://{host}/v0/postings/{board}?mode=json")
    out = []
    for j in d:
        lists = "\n".join(f"{x.get('text', '')}\n{strip_html(x.get('content', ''))}" for x in j.get("lists", []))
        text = "\n".join(filter(None, [j.get("descriptionPlain"), lists, j.get("additionalPlain")]))
        out.append(posting("ats:lever", j["text"], company, (j.get("categories") or {}).get("location", ""),
                           j["hostedUrl"], _date(j.get("createdAt")), text))
    return out


def fetch_ashby(board, company):
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    out = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [x.get("location", "") for x in j.get("secondaryLocations") or []]
        out.append(posting("ats:ashby", j["title"], company, " / ".join(x for x in locs if x), j["jobUrl"],
                           _date(j.get("publishedAt")), j.get("descriptionPlain") or strip_html(j.get("descriptionHtml"))))
    return out


def fetch_personio(board, company):
    xml = None
    for tld in ("de", "com"):
        try:
            xml = http_get(f"https://{board}.jobs.personio.{tld}/xml").decode("utf-8", "replace")
            break
        except urllib.error.HTTPError:
            continue
    if xml is None:
        raise RuntimeError("no personio feed")
    out = []
    for pos in re.findall(r"<position>(.*?)</position>", xml, re.S):
        def tag(name):
            m = re.search(rf"<{name}>(.*?)</{name}>", pos, re.S)
            return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""
        pid = tag("id")
        text = "\n".join(strip_html(html.unescape(v)) for v in re.findall(r"<value>(.*?)</value>", pos, re.S))
        text = re.sub(r"<!\[CDATA\[|\]\]>", "", text)
        out.append(posting("ats:personio", tag("name"), tag("subcompany") or company, tag("office"),
                           f"https://{board}.jobs.personio.de/job/{pid}", _date(tag("createdAt")), text))
    return out


def fetch_recruitee(board, company):
    d = http_json(f"https://{board}.recruitee.com/api/offers/")
    out = []
    for j in d.get("offers", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("country")) if x) or j.get("location", "")
        text = strip_html((j.get("description") or "") + "\n" + (j.get("requirements") or ""))
        out.append(posting("ats:recruitee", j["title"], j.get("company_name") or company, loc,
                           j.get("careers_url") or "", _date(j.get("published_at") or j.get("created_at")), text))
    return out


def fetch_smartrecruiters(board, company, wanted=None):
    """Large employers live here (Bosch alone lists thousands), so list per country and fetch
    the full text only for postings the caller wants."""
    out = []
    for cc in (countries.iso(c) for c in config.get().countries):  # filtered server-side by country
        offset = 0
        while True:
            d = http_json(f"https://api.smartrecruiters.com/v1/companies/{board}/postings?country={cc}&limit=100&offset={offset}")
            items = d.get("content", [])
            for j in items:
                loc = j.get("location") or {}
                where = ", ".join(x for x in (loc.get("city"), (loc.get("country") or "").upper()) if x)
                name = (j.get("company") or {}).get("name") or company
                if wanted and not wanted(j["name"], name, where):
                    continue
                det = http_json(f"https://api.smartrecruiters.com/v1/companies/{board}/postings/{j['id']}")
                secs = ((det.get("jobAd") or {}).get("sections") or {})
                text = "\n".join(strip_html((secs.get(k) or {}).get("text", "")) for k in
                                 ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
                url = det.get("postingUrl") or f"https://jobs.smartrecruiters.com/{board}/{j['id']}"
                out.append(posting("ats:smartrecruiters", j["name"], name, where, url, _date(j.get("releasedDate")), text))
                time.sleep(0.3)
            offset += len(items)
            if not items or offset >= d.get("totalFound", 0):
                break
            time.sleep(0.5)
    return out


FETCHERS = {
    "greenhouse": fetch_greenhouse, "lever": fetch_lever, "lever_eu": lambda b, c: fetch_lever(b, c, eu=True),
    "ashby": fetch_ashby, "personio": fetch_personio, "recruitee": fetch_recruitee,
}


def fetch_board(ats, board, company, wanted=None):
    if ats == "smartrecruiters":
        return fetch_smartrecruiters(board, company, wanted)
    return FETCHERS[ats](board, company)


# ---------------------------------------------------------------- daily collector entry point
def seed_from_profile(reg, profile, log=print):
    """Add the boards listed in [search] company_boards ("greenhouse:stripe", "lever:spotify"),
    so you can follow any company in any country from day one. Returns how many were new."""
    added = 0
    for item in profile.search.get("company_boards", []):
        ats, _, board = str(item).partition(":")
        ats, board = ats.strip().lower(), board.strip()
        if ats not in ATS_NAMES or not board:
            log(f"  ats: ignored company_boards entry {item!r} (use <system>:<board>, system one of {', '.join(ATS_NAMES)})")
            continue
        key = board_key(ats, board)
        if key not in reg["boards"]:
            reg["boards"][key] = {"ats": ats, "board": board, "company": board, "source": "profile",
                                  "first_seen": today(), "enabled": True}
            added += 1
        elif not reg["boards"][key].get("enabled", True) and reg["boards"][key].get("source") == "profile":
            reg["boards"][key].update(enabled=True, fails=0)
    return added


def collect(wanted, log=print, delay=1.5):
    """Pull every enabled board. Every open role a board lists is offered to `wanted`
    (no date window: an open role is worth seeing the first time we find its board)."""
    reg = load_registry()
    seeded = seed_from_profile(reg, config.get(), log=log)
    if seeded:
        log(f"  ats: {seeded} boards added from your profile's company_boards")
    out, ok, failed = [], 0, 0
    # career feeds are global: only a positively recognised in-scope location counts
    # (otherwise São Paulo, Cape Town or "Remote - US" would be read as your default country)
    profile = config.get()
    in_scope = lambda title, company, loc: profile.country_of(loc, strict=True) is not None and wanted(title, company, loc)
    for key, b in sorted(reg["boards"].items()):
        if not b.get("enabled", True):
            continue
        try:
            postings = fetch_board(b["ats"], b["board"], b.get("company") or b["board"], in_scope)
            kept = [p for p in postings if b["ats"] == "smartrecruiters" or in_scope(p["title"], p["company"], p["location"])]
            out += kept
            b.update(last_ok=today(), last_count=len(postings), fails=0)
            ok += 1
        except (urllib.error.HTTPError, urllib.error.URLError, RateLimited, RuntimeError, ValueError, KeyError) as e:
            b["fails"] = b.get("fails", 0) + 1
            b["last_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            if b["fails"] >= 5:
                b["enabled"] = False
                log(f"  ats: disabled {key} after 5 failed days ({b['last_error']})")
            failed += 1
        time.sleep(delay)
    save_registry(reg)
    log(f"ats: {ok} boards read, {failed} failed, {len(out)} wanted postings")
    return out


# ---------------------------------------------------------------- discovery
def harvest(log=print):
    """Add every board referenced by a stored URL or cached posting text."""
    reg = load_registry()
    _, seen_path, jd_cache = _paths()
    with open(seen_path, encoding="utf-8") as f:
        seen = json.load(f)["seen"]
    found = {}
    for key, v in seen.items():
        for ats, board in boards_in_text(f"{key} {v.get('url', '')}"):
            found.setdefault(board_key(ats, board), (ats, board, v.get("company")))
    if os.path.isdir(jd_cache):
        for name in os.listdir(jd_cache):
            with open(os.path.join(jd_cache, name), encoding="utf-8", errors="replace") as f:
                for ats, board in boards_in_text(f.read()):
                    found.setdefault(board_key(ats, board), (ats, board, None))
    added = 0
    for key, (ats, board, company) in found.items():
        if key not in reg["boards"]:
            reg["boards"][key] = {"ats": ats, "board": board, "company": company, "source": "harvest",
                                  "first_seen": today(), "enabled": True}
            added += 1
    save_registry(reg)
    log(f"ats harvest: {added} new boards from stored URLs and texts ({len(reg['boards'])} total)")
    return added


LEGAL = re.compile(r"\b(gmbh|ag|se|kg|kgaa|co|& co|mbh|ug|ltd|limited|inc|llc|bv|b\.v\.|nv|sp\. z o\.o\.|sa|group|holding|"
                   r"germany|deutschland|europe|international|services|technologies|technology|solutions)\b\.?", re.I)


def slug_guesses(company):
    base = LEGAL.sub(" ", (company or "").lower())
    base = re.sub(r"[^a-z0-9äöüß ]+", " ", base)
    base = base.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    words = base.split()
    if not words:
        return []
    guesses = ["".join(words), "-".join(words)]
    if len(words) > 1:
        guesses.append(words[0])
    return list(dict.fromkeys(g for g in guesses if len(g) >= 3))


def _norm_title(t):
    t = re.sub(r"\((?:[mwfdxa]\s*[/|,_]\s*)+[mwfdxa]\)|\((?:all genders?|gn|d|divers)[^)]*\)", "", (t or "").lower())
    return re.sub(r"[^a-z0-9äöüß]+", " ", t).strip()


def probe(budget=600, log=print, delay=1.0):
    """Guess boards for companies seen elsewhere; accept only on a title match."""
    reg = load_registry()
    with open(_paths()[1], encoding="utf-8") as f:
        seen = json.load(f)["seen"]
    titles = {}
    for v in seen.values():
        if v.get("company") and v.get("title"):
            titles.setdefault(v["company"], set()).add(_norm_title(v["title"]))
    known_companies = {(b.get("company") or "").lower() for b in reg["boards"].values()}
    cutoff = (datetime.date.today() - datetime.timedelta(days=RETRY_DAYS)).isoformat()
    requests_used, added = 0, 0
    order = ["personio", "greenhouse", "ashby", "lever", "lever_eu", "recruitee"]
    for company, wanted_titles in sorted(titles.items(), key=lambda kv: -len(kv[1])):
        if company.lower() in known_companies:
            continue
        for slug in slug_guesses(company):
            hit = False
            for ats in order:
                pk = board_key(ats, slug)
                if pk in reg["boards"] or reg["probed"].get(pk, "") >= cutoff:
                    continue
                if requests_used >= budget:
                    save_registry(reg)
                    log(f"ats probe: budget used ({requests_used} requests), {added} boards added")
                    return added
                requests_used += 1
                reg["probed"][pk] = today()
                try:
                    postings = fetch_board(ats, slug, company)
                except (urllib.error.HTTPError, urllib.error.URLError, RateLimited, RuntimeError, ValueError, KeyError):
                    time.sleep(delay)
                    continue
                time.sleep(delay)
                if any(_norm_title(p["title"]) in wanted_titles for p in postings):
                    reg["boards"][pk] = {"ats": ats, "board": slug, "company": company, "source": "probe",
                                         "first_seen": today(), "enabled": True}
                    known_companies.add(company.lower())
                    added += 1
                    hit = True
                    break
            if hit:
                break
    save_registry(reg)
    log(f"ats probe: {requests_used} requests, {added} boards added ({len(reg['boards'])} total)")
    return added


# ---------------------------------------------------------------- englishjobs.de snippets -> full posting
def titles_match(a, b):
    """Same role under small wording differences ("Junior CRM Manager (m/w/d)" vs "Junior CRM Manager")."""
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return False
    if na == nb or na.startswith(nb) or nb.startswith(na):
        return True
    sa, sb = set(na.split()), set(nb.split())
    return len(sa & sb) / max(len(sa | sb), 1) >= 0.8


def _company_key(company):
    return " ".join(re.sub(r"[^a-z0-9äöüß ]+", " ", LEGAL.sub(" ", (company or "").lower())).split())


def resolve_snippets(seen, statuses=("new",), budget=400, log=print, delay=1.0):
    """englishjobs.de lists only a snippet, and its job links may not be fetched automatically,
    so find the same role on the employer's own career feed and store that full text instead.
    Known boards are tried first; otherwise the company's board is guessed (same title-match
    rule as probe), which also grows the registry. Returns the resolved count."""
    reg = load_registry()
    jd_cache = _paths()[2]
    by_company = {}
    for bk, b in reg["boards"].items():
        if b.get("enabled", True) and b.get("company"):
            by_company.setdefault(_company_key(b["company"]), []).append(bk)
    cutoff = (datetime.date.today() - datetime.timedelta(days=RETRY_DAYS)).isoformat()
    order = ["personio", "greenhouse", "ashby", "lever", "lever_eu", "recruitee"]
    feed_cache, requests_used, resolved = {}, 0, 0

    def feed(bk, title):
        b = reg["boards"][bk]
        if b["ats"] == "smartrecruiters":  # huge boards: fetch only the matching posting's text
            return fetch_board("smartrecruiters", b["board"], b.get("company") or "", lambda t, c, l: titles_match(t, title))
        if bk not in feed_cache:
            try:
                feed_cache[bk] = fetch_board(b["ats"], b["board"], b.get("company") or b["board"])
            except (urllib.error.HTTPError, urllib.error.URLError, RateLimited, RuntimeError, ValueError, KeyError):
                feed_cache[bk] = []
            time.sleep(delay)
        return feed_cache[bk]

    for key, v in seen.items():
        if not v.get("jd_snippet_only") or v.get("status") not in statuses:
            continue
        ck = _company_key(v.get("company"))
        hit = None
        for bk in by_company.get(ck, []):
            hit = next((p for p in feed(bk, v["title"]) if titles_match(p["title"], v["title"])), None)
            if hit:
                break
        for slug in ([] if hit else slug_guesses(v.get("company"))):
            for ats in order:
                pk = board_key(ats, slug)
                if pk in reg["boards"] or reg["probed"].get(pk, "") >= cutoff or requests_used >= budget:
                    continue
                requests_used += 1
                reg["probed"][pk] = today()
                try:
                    postings = fetch_board(ats, slug, v.get("company"))
                except (urllib.error.HTTPError, urllib.error.URLError, RateLimited, RuntimeError, ValueError, KeyError):
                    time.sleep(delay)
                    continue
                time.sleep(delay)
                hit = next((p for p in postings if titles_match(p["title"], v["title"])), None)
                if hit:
                    reg["boards"][pk] = {"ats": ats, "board": slug, "company": v.get("company"), "source": "resolve",
                                         "first_seen": today(), "enabled": True}
                    feed_cache[pk] = postings
                    by_company.setdefault(ck, []).append(pk)
                    break
            if hit:
                break
        if hit and hit.get("text") and hit.get("url"):
            name = os.path.basename(v.get("jd_cache") or "") or (re.sub(r"[^a-z0-9]+", "", key.lower())[:40] + ".txt")
            os.makedirs(jd_cache, exist_ok=True)
            with open(os.path.join(jd_cache, name), "w", encoding="utf-8") as f:
                f.write(hit["text"])
            v.update(englishjobs_url=v.get("url"), url=hit["url"], jd_cache=name,
                     resolved_from=hit["source"])
            v.pop("jd_snippet_only", None)
            resolved += 1
    save_registry(reg)
    log(f"englishjobs snippets: {resolved} resolved to the employer's own posting ({requests_used} guess requests)")
    return resolved


ATS_NAMES = sorted(list(FETCHERS) + ["smartrecruiters"])


def cli(args):
    """`python radar.py ats <harvest|probe|list|add>`."""
    if args.ats_cmd == "harvest":
        harvest()
    elif args.ats_cmd == "probe":
        probe(args.budget)
    elif args.ats_cmd == "list":
        reg = load_registry()
        by = {}
        for b in reg["boards"].values():
            by.setdefault(b["ats"], []).append(b)
        for ats, items in sorted(by.items()):
            print(f"{ats}: {len(items)} boards, {sum(1 for b in items if not b.get('enabled', True))} disabled")
        if not by:
            print("no boards yet: they are found automatically during collection")
    elif args.ats_cmd == "add":
        reg = load_registry()
        reg["boards"][board_key(args.ats, args.board)] = {"ats": args.ats, "board": args.board, "company": args.company,
                                                          "source": "manual", "first_seen": today(), "enabled": True}
        save_registry(reg)
        print("added", board_key(args.ats, args.board))
