"""Your profile (profile/profile.toml) and every rule derived from it.

All personal choices live in the profile: who you are (the summary the ranking agents
read), where you can work, which languages you speak at which level, which job titles
are in your directions, and which search terms to run. The code holds only the generic
machinery. `python radar.py profile-check` shows what your profile resolves to.

Paths can be redirected with environment variables, which the tests use:
JOB_RADAR_PROFILE (the profile file) and JOB_RADAR_DATA (the data folder).
"""
import os
import re
import tomllib

from . import countries

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(ROOT, "profile")
EXAMPLE_PROFILE = os.path.join(PROFILE_DIR, "profile.example.toml")
REPORTS = os.path.join(ROOT, "reports")
DASHBOARD = os.path.join(REPORTS, "dashboard.html")
DAILY = os.path.join(REPORTS, "daily")


def profile_path():
    return os.environ.get("JOB_RADAR_PROFILE") or os.path.join(PROFILE_DIR, "profile.toml")


def data_dir():
    return os.environ.get("JOB_RADAR_DATA") or os.path.join(ROOT, "data")


def data(*parts):
    return os.path.join(data_dir(), *parts)


def rel(path):
    """Path relative to the repo for messages, or absolute when it is elsewhere (another drive)."""
    try:
        r = os.path.relpath(path, ROOT)
    except ValueError:
        return path
    return path if r.startswith("..") else r


# Paths inside the data folder (all git-ignored).
SEEN = "seen_jobs.json"
JD_CACHE = "jd_cache"
RUNS = "runs"
LOCK = ".seen_jobs.lock"
TRACKER = "applications.csv"
REGISTRY = "ats_registry.json"
PREFS = "preferences.json"
RANK_BATCHES = "rank_batches"
VERIFY_BATCHES = "verify_batches"

LEVELS = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6, "native": 7}
LEVEL_NAMES = {v: k.upper() if k != "native" else "native" for k, v in LEVELS.items()}
STAGES = ("student", "graduate", "experienced")

# Titles that are another track, not a regular job, for anyone.
BASE_TRACKS = ["ausbildung", "azubi", "auszubildende*", "duales studium", "dualer student", "duale studentin",
               "dual study", "minijob", "freelance*", "aushilfe", "thesis", "abschlussarbeit", "masterarbeit",
               "bachelorarbeit"]
# Student jobs that require current enrollment, so they are skipped once you have graduated.
STUDENT_ONLY_TRACKS = ["werkstudent*", "working student", "work student"]
# Postings that match a direction keyword but are not office jobs.
DEFAULT_NOISE = ["warehouse", "lager", "lagermitarbeiter", "lagerhelfer", "lagerarbeiter", "lagerlogistik",
                 "fulfilment associate", "fulfillment associate", "picker", "packer", "kommissionier*", "fahrer",
                 "driver", "reinigung", "cleaner", "mechanic", "mechaniker", "techniker", "verkäufer", "cashier",
                 "kassierer", r"re:up ?to \$\d+", r"re:\$\d+ ?/ ?h(ou)?r", r"re:fully remote \|"]
# Quota-carrying sales titles that are senior in practice even without the word "Senior".
SENIOR_SALES = re.compile(r"\b(enterprise|strategic|major|mid[- ]?market|named|global) account (executive|manager|director)", re.I)


def keyword_pattern(word):
    """One profile keyword as a regex. Plain keywords match whole words or phrases,
    case-insensitively ("crm" matches "CRM Manager" but not "Scrum"); a trailing "*" makes
    it a prefix ("analy*" matches analyst and analytics); "re:" starts a raw regex."""
    w = (word or "").strip()
    if w.startswith("re:"):
        return w[3:]
    prefix = w.endswith("*")
    body = re.escape(w.rstrip("*").strip()).replace(r"\ ", r"\s+")
    return r"(?<!\w)" + body + ("" if prefix else r"(?!\w)")


def keywords_regex(words):
    words = [w for w in (words or []) if str(w).strip()]
    if not words:
        return None
    return re.compile("|".join(f"(?:{keyword_pattern(w)})" for w in words), re.I)


class ProfileError(SystemExit):
    pass


class Profile:
    def __init__(self, raw, path=""):
        self.raw, self.path = raw, path
        c = raw.get("candidate", {})
        self.name = c.get("name", "")
        self.summary = (c.get("summary") or "").strip()
        self.stage = c.get("career_stage", "graduate")
        if self.stage not in STAGES:
            raise ProfileError(f"candidate.career_stage must be one of {STAGES}, not {self.stage!r}")
        self.years = float(c.get("years_experience", 0))

        s = raw.get("scope", {})
        self.countries = [x.upper() for x in s.get("countries", ["DE"])]
        default_interns = [] if self.stage == "experienced" else self.countries[:1]
        self.internship_countries = [x.upper() for x in s.get("internship_countries", default_interns)]
        self.work_permit_countries = [x.upper() for x in s.get("work_permit_countries", self.countries[:1])]
        self.unknown_location = (s.get("unknown_location", self.countries[0]) or "").upper()
        for code in self.countries + self.internship_countries + self.work_permit_countries:
            if code not in countries.COUNTRIES:
                raise ProfileError(f"unknown country code {code!r}; supported: {', '.join(countries.COUNTRIES)}")

        self.languages = {}
        for lang, level in raw.get("languages", {}).items():
            lv = LEVELS.get(str(level).strip().lower())
            if lv is None:
                raise ProfileError(f"languages.{lang} = {level!r}: use A1-C2 or \"native\"")
            self.languages[lang.lower()] = lv

        r = raw.get("rules", {})
        self.skip_years = int(r.get("skip_if_years_at_least", 3))
        self.skip_senior = bool(r.get("skip_senior_titles", self.stage != "experienced"))
        self.skip_senior_sales = bool(r.get("skip_senior_sales_titles", self.stage != "experienced"))
        tracks = BASE_TRACKS + ([] if self.stage == "student" else STUDENT_ONLY_TRACKS)
        self.excluded_track = keywords_regex(r.get("excluded_title_words", tracks))
        self.noise = keywords_regex(DEFAULT_NOISE + list(r.get("extra_noise_title_words", [])))
        self.german_jd_policy = r.get("german_jd_policy", "soft-only")
        if self.german_jd_policy not in ("skip", "soft-only", "keep"):
            raise ProfileError("rules.german_jd_policy must be skip, soft-only or keep")
        self.enrolled_only_companies = list(r.get("enrolled_only_internship_companies", []))

        dirs = raw.get("directions", {})
        if not dirs:
            raise ProfileError("the profile needs at least one [directions] group")
        self.directions = {name: keywords_regex(words) for name, words in dirs.items() if keywords_regex(words)}

        adv = raw.get("advantage", {})
        self.advantage = keywords_regex(adv.get("keywords", []))
        self.advantage_label = adv.get("label", "advantage")
        self.advantage_companies = [x.lower() for x in adv.get("companies", []) if len(x) >= 3]

        self.search = raw.get("search", {})
        self.digest = raw.get("digest", {})
        self.budgets = raw.get("budgets", {})

    # ------------------------------------------------------------ languages
    def level(self, lang):
        return self.languages.get(lang, 0)

    @property
    def german_gate(self):
        """German requirements are checked only when your German is below C1."""
        return self.level("german") < LEVELS["c1"]

    def speaks(self, lang, at_least="b2"):
        return self.level(lang) >= LEVELS[at_least]

    def language_summary(self):
        return ", ".join(f"{lang.capitalize()} {LEVEL_NAMES[lv]}" for lang, lv in
                         sorted(self.languages.items(), key=lambda kv: -kv[1])) or "not stated"

    # ------------------------------------------------------------ titles and places
    def families_of(self, title):
        return [name for name, rx in self.directions.items() if rx.search(title or "")]

    def country_of(self, location, strict=False):
        return countries.country_of(location, self.countries, self.unknown_location, strict=strict)

    def has_advantage(self, text, company=""):
        if self.advantage and self.advantage.search(text or ""):
            return True
        low = (company or "").lower()
        return any(c in low for c in self.advantage_companies)

    def search_value(self, key, default):
        return self.search.get(key, default)

    def budget(self, key, default):
        return int(self.budgets.get(key, default))


_cached = None


def load(path=None):
    path = path or profile_path()
    if not os.path.exists(path):
        raise ProfileError(
            f"No profile at {rel(path)}.\n"
            "Run /setup in Claude Code (it reads your CV and writes the profile), or copy "
            "profile/profile.example.toml to profile/profile.toml and edit it.")
    with open(path, "rb") as f:
        try:
            raw = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ProfileError(f"{rel(path)} is not valid TOML: {e}")
    return Profile(raw, path)


def get():
    """The active profile, loaded once per process."""
    global _cached
    if _cached is None or _cached.path != profile_path():
        _cached = load()
    return _cached


def reset():
    global _cached
    _cached = None
