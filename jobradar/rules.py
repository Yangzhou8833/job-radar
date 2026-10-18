"""Deterministic title and text rules shared by the collector and the pre-screen.

Everything here is generic; what applies to you is decided by your profile (see
jobradar/config.py): your direction keywords, career stage, years threshold and
languages. The patterns cover English and German postings, because the sources are
strongest for Germany.
"""
import re

GENDER_TAG = re.compile(r"\((?:[mwfdxa]\s*[/|,_]\s*)+[mwfdxa]\)|\((?:all genders?|gn|d|divers)[^)]*\)", re.I)


def normalize_listing(text):
    """Lowercase, drop gender tags like (m/w/d) / (all genders), strip punctuation."""
    text = GENDER_TAG.sub("", (text or "").lower())
    return re.sub(r"[^a-z0-9äöüß]+", " ", text).strip()


def norm_key(company, title):
    return f"{normalize_listing(company)}|{normalize_listing(title)}"


# ---------------------------------------------------------------- titles
# A seniority word at the start of the title, or a leadership noun anywhere.
# "(Senior)" / "(Sr.)" in parentheses means "junior or senior" and is left to the ranking.
SENIOR_TITLE = re.compile(
    r"(^\s*(senior|sr\.?|experienced)\b)"
    r"|(?<![(\w])(senior|sr\.)\s+(?!\))"
    r"|\b(head of|principal|director|vice president|vp)\b"
    r"|\blead\b(?!\s*(gen|generation|management|nurtur|qualif))|\bleader\b"
    r"|\b(teamleit\w*|abteilungsleit\w*|bereichsleit\w*|leiter\w*|leitung)\b",
    re.I,
)
PAREN_SENIOR = re.compile(r"\(\s*(senior|sr\.?)\s*\)", re.I)
JUNIOR_HINT = re.compile(r"\b(junior|jr\.?|graduate|trainee|entry|associate|assistant|intern|praktik|werkstudent)\b", re.I)
INTERNSHIP_TITLE = re.compile(r"praktik|\bintern\b|internship|\bpraktikant", re.I)
MANDATORY_OR_UNPAID = re.compile(r"mandatory|pflicht|compulsory|unpaid|unbezahlt", re.I)
SENIOR_SALES = re.compile(r"\b(enterprise|strategic|major|mid[- ]?market|named|global) account (executive|manager|director)", re.I)


def title_is_senior(title):
    # drop gender tags first: "Head (f/m/d) of Service Operations" hid "head of"
    t = GENDER_TAG.sub(" ", PAREN_SENIOR.sub(" ", title or ""))
    return bool(SENIOR_TITLE.search(re.sub(r"\s+", " ", t)))


def senior_skip(title, profile):
    return profile.skip_senior and title_is_senior(title) and not JUNIOR_HINT.search(title or "")


def title_rejection(title, profile):
    """Reason string when the title alone rules the posting out, else None. Seniority is
    checked separately (senior_skip) so it keeps its own counter."""
    t = title or ""
    if profile.excluded_track and profile.excluded_track.search(t):
        return "other track (Werkstudent / Ausbildung / thesis / freelance)"
    if INTERNSHIP_TITLE.search(t) and MANDATORY_OR_UNPAID.search(t) and profile.stage != "student":
        return "mandatory or unpaid internship"
    if profile.noise and profile.noise.search(t):
        return "non-office or gig-work title"
    if profile.skip_senior_sales and SENIOR_SALES.search(t):
        return "senior sales title"
    if not profile.families_of(t):
        return "title outside your directions"
    return None


# ---------------------------------------------------------------- years of experience
YEARS = re.compile(
    r"(?:at least|minimum(?: of)?|min\.?|mindestens|more than|over|über)?\s*"
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to|bis)\s*(\d{1,2})\s*\+?)?\s*"
    r"(?:years?|yrs?|jahre?n?)\b(?:[^.\n]{0,60}?)"
    r"(experience|erfahrung|berufserfahrung|working|in (?:a|the) )",
    re.I,
)
MEHRJAEHRIG = re.compile(r"\bmehrjährige[rn]?\s+(berufs)?erfahrung|several years of (professional |relevant |work )?experience", re.I)
WORD_NUM = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ten": 10,
            "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6}
YEARS_IN = re.compile(r"\b(\d{1,2})\s*\+\s*(?:years?|yrs?|jahre?n?)\b", re.I)
YEARS_WORD = re.compile(
    r"\b(two|three|four|five|six|seven|eight|ten|zwei|drei|vier|fünf|sechs)\s*(?:\(\d+\)\s*)?(?:\+\s*)?"
    r"(?:years?'?|jahre?n?)\b(?:[^.\n]{0,60}?)(experience|erfahrung|berufserfahrung|in (?:a|the)\b|of\b)", re.I)


def _career_path(text, pos):
    """True when the number describes where the role leads, not what it requires:
    "a global career ... after approximately 3-4 years in the Business Strategy Team"."""
    return bool(re.search(r"\b(after|nach|within|innerhalb|for the first|in den ersten|during)\b[^.\n]{0,20}$",
                          text[max(0, pos - 40):pos], re.I))


def years_requirement(text):
    """(min_years, evidence) for the strongest explicit requirement, or (None, None)."""
    text = text or ""
    best = None
    for m in YEARS.finditer(text):
        lo = int(m.group(1))
        if lo > 15 or _career_path(text, m.start(1)):
            continue
        if best is None or lo > best[0]:
            best = (lo, m.group(0).strip()[:90])
    for m in YEARS_IN.finditer(text):
        lo = int(m.group(1))
        if lo > 15 or _career_path(text, m.start(1)):
            continue
        # "1–3+ years" is a 1-year bar: the number after a range dash is the upper end
        if re.search(r"\d\s*(?:-|–|to|bis)\s*$", text[max(0, m.start(1) - 6):m.start(1)]):
            continue
        # a bare "N+ years" counts only when it reads as a requirement ("5+ years in account
        # management"), not as company copy ("4+ Jahre Hypergrowth")
        if not re.match(r"[^.\n]{0,15}?\b(in|of|as|im|in der|als|experience|erfahrung|berufserfahrung|working)\b",
                        text[m.end():m.end() + 40], re.I):
            continue
        if best is None or lo > best[0]:
            best = (lo, m.group(0).strip()[:90])
    for m in YEARS_WORD.finditer(text):
        lo = WORD_NUM[m.group(1).lower()]
        if best is None or lo > best[0]:
            best = (lo, m.group(0).strip()[:90])
    if best is None:
        m = MEHRJAEHRIG.search(text)
        if m:
            return 3, m.group(0)
    return best if best else (None, None)


# ---------------------------------------------------------------- German requirements
GERMAN_REQUIRED = re.compile(
    r"\b(?:fluent|fluency|business[- ]fluent|excellent|very good|strong|native(?:[- ]level)?|professional)"
    r"[\w ,()/-]{0,25}?\bgerman\b"
    r"|\bgerman\b[\w ,()/-]{0,20}?\b(?:c1|c2|native|mother tongue|fluent|fluency|is a must|must-have|required|mandatory)\b"
    r"|\b(?:english and german|german and english)\b[\w ,()/-]{0,25}?\b(?:required|a must|mandatory|fluent|excellent|very good)\b"
    r"|verhandlungssicher|fließend\w*\s+deutsch|deutsch\w*\s+(?:fließend|c1|c2|verhandlungssicher)"
    r"|deutsch[\w ,/-]{0,30}?\bfließend|(?:sehr gute|exzellente|ausgezeichnete|perfekte|hervorragende)\s+deutsch|muttersprach",
    re.I,
)
# An explicit statement that German is wanted only at a soft level.
SOFT_GERMAN = re.compile(
    r"(?:gute|solide|erste|grundlegende)\s+deutschkenntnisse|deutschkenntnisse\s+(?:auf\s+)?(?:niveau\s+)?(?:a2|b1|b2)"
    r"|deutsch\w*\s*(?:\(|auf\s+niveau\s+|niveau\s+)?(?:a2|b1|b2)\b|grundkenntnisse\s+(?:in\s+)?deutsch"
    r"|deutsch(?:kenntnisse)?\s+(?:sind|ist|wären)\s+(?:von\s+vorteil|wünschenswert|ein\s+plus)"
    r"|deutsch(?:kenntnisse)?\s+(?:von\s+vorteil|wünschenswert)|german\s+(?:is\s+)?(?:a\s+)?(?:plus|nice to have|an advantage)"
    r"|basic\s+german|(?:good|conversational)\s+german|german\s*\(?(?:a2|b1|b2)\b", re.I)


def german_required(text):
    """The matched wording when the posting demands fluent (C1+) German, else None."""
    m = GERMAN_REQUIRED.search(text or "")
    return m.group(0).strip()[:90] if m else None


# ---------------------------------------------------------------- internships (graduates)
INTERNSHIP_ANY = re.compile(r"praktik|intern\b|internship|werkstudent|working student|trainee.*student", re.I)
# Wording that rules an internship out for someone who has graduated, whatever else it says.
INTERN_HARD_BLOCK = re.compile(
    r"pflicht-?praktik\w*|verpflichtende[sn]? praktikum|mandatory internship|compulsory internship"
    r"|curricular internship|required internship as part of|working student|werkstudent\w*", re.I)
ENROLLMENT = re.compile(
    r"eingeschrieben|immatrikul|pflicht-?praktik|verpflichtende[sn]? praktikum"
    r"|im rahmen (?:deines|deiner|eines|des) (?:studiums|pflicht)"
    r"|während (?:deines|des) studiums|du studierst|aktuell studierst"
    r"|currently enrolled|must be enrolled|enrolled (?:in|as|at)|enrollment|enrolment"
    r"|currently pursuing|mandatory internship|compulsory internship|student status|studentenstatus",
    re.I,
)
# Positive confirmation that a graduate can take the internship. Stricter than a bare
# "graduate", which also matches "graduate students" and "undergraduate".
GRAD_CONFIRMED = re.compile(
    r"absolvent|recent(?:ly)? graduat|graduates? (?:are )?(?:welcome|eligible|may apply|can apply|are also welcome)"
    r"|or (?:a )?(?:recent )?graduate\b|have (?:already |recently )?graduated|completed (?:your |a )?(?:bachelor|master|university degree|degree|studies)"
    r"|nach (?:dem|deinem|ihrem) (?:abgeschlossenen )?studium|abgeschlossene[sn]? (?:bachelor|master|studium|hochschulstudium)"
    r"|after (?:your|completing your|finishing your) (?:studies|degree)|post-?graduate internship|graduate internship"
    r"|berufseinsteiger|nach abschluss|within the last \d+ years?|im anschluss an (?:dein|das) studium", re.I)


def enrollment_required(title, text):
    """The matched enrollment wording when an internship clearly requires current enrollment."""
    if not INTERNSHIP_ANY.search(title or ""):
        return None
    hay = f"{title}\n{text or ''}"
    m = ENROLLMENT.search(hay)
    if not m or GRAD_CONFIRMED.search(hay):
        return None
    start = max(0, m.start() - 40)
    return hay[start:m.end() + 40].replace("\n", " ").strip()


def internship_unconfirmed(title, text, employment_type=""):
    """An internship whose text never confirms that graduates can apply. Graduate
    programmes and trainee schemes are not internships and are never caught here."""
    is_intern = bool(INTERNSHIP_TITLE.search(title or "")) or (employment_type or "").lower() == "internship"
    return is_intern and not GRAD_CONFIRMED.search(text or "")


def enrolled_only_company(company, profile):
    return any(re.search(rf"\b{re.escape(n)}\b", company or "", re.I) for n in profile.enrolled_only_companies)


# ---------------------------------------------------------------- work authorization
# Used outside your work_permit_countries: a posting that requires a local permit or right to
# work, or says it does not sponsor visas. Silence on work authorization is not a reason to skip.
WORK_PERMIT_REQUIRED = re.compile(
    r"(?:must|need to|required to|should) (?:already )?(?:have|hold|possess) (?:a |the |an )?(?:valid )?"
    r"(?:work(?:ing)? permit|right to work|work authori[sz]ation|residence permit|eu (?:citizenship|passport))"
    r"|(?:valid )?(?:work(?:ing)? permit|right to work|work authori[sz]ation)[^.\n]{0,40}(?:is |are )?(?:required|mandatory|a must|necessary)"
    r"|(?:do|does|can|will|are) not (?:able to )?(?:offer |provide )?(?:visa )?sponsor"
    r"|(?:unable|not able) to (?:offer |provide )?(?:visa )?sponsor|no (?:visa )?sponsorship"
    r"|eu(?:/eea)? (?:citizenship|citizens? only|passport) (?:is )?required|only (?:eu|eea) citizens"
    r"|without (?:the need for )?(?:visa )?sponsorship"
    r"|arbeitserlaubnis (?:ist )?(?:erforderlich|voraussetzung)|gültige arbeitsbewilligung"
    r"|werkvergunning (?:is )?vereist|pozwolenie na pracę", re.I)
