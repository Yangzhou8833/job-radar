"""Detect the language a job description is written in, without an LLM.

Counts common function words ("und", "der", "mit" vs. "and", "the", "with"). German and
English job ads both use plenty of English loanwords ("Brand Manager", "Power BI",
"Stakeholder"), but their function words do not overlap, so the ratio is a reliable
signal even on short texts. Dutch and Polish are recognised too.

Result fields:
    lang        "en" | "de" | "mixed" | "unknown" | "nl" | "pl"
    de_ratio    share of German function words among the German + English ones
    english_ok  True if the text says English is the working language
                ("working language is English", "Arbeitssprache Englisch",
                "no German required")
"""
import re

DE = set("""und der die das den dem des mit für wir sie ihr ihre ihren unsere unser unseren
eine einen einem einer ein von zu zum zur auf im bei ist sind oder als dich du dein deine deinen
uns werden wird auch nicht über nach aus sowie bzw durch wenn wie was hast bist kannst bieten
suchen erfahrung kenntnisse aufgaben deutschkenntnisse englischkenntnisse""".split())
EN = set("""and the with for we you your our a an of to in on at is are or as will be this that
from by have has who what can offer looking experience skills responsibilities""".split())
NL = set("""de het een en van voor met wij jij je jouw onze ons zijn bent heb hebt naar bij als ook
niet aan dat wat wie werk ervaring kennis functie vacature solliciteer""".split())
PL = set("""i w na z do dla oraz jest są się nie że od jak lub przez twoje nasz nasze nasza naszego
będziesz oferujemy wymagania doświadczenie znajomość praca pracy zespół""".split())

ENGLISH_OK = re.compile(
    r"(working language (is|will be) english|english[- ]speaking (team|environment|company)"
    r"|our (company|team) language is english|corporate language (is )?english"
    r"|no german (required|needed|necessary)|german (is )?(not required|a plus|nice to have|is a bonus)"
    r"|arbeitssprache (ist )?englisch|unternehmenssprache (ist )?englisch"
    r"|deutschkenntnisse sind (kein muss|nicht erforderlich|von vorteil))",
    re.I,
)


def detect(text):
    words = re.findall(r"[a-zäöüßąćęłńóśźż]+", (text or "").lower())
    de = sum(1 for w in words if w in DE)
    en = sum(1 for w in words if w in EN)
    nl = sum(1 for w in words if w in NL and w not in EN and w not in DE)
    pl = sum(1 for w in words if w in PL and w not in EN)
    total = de + en
    if max(nl, pl) >= 12 and max(nl, pl) > 1.5 * max(de, en):
        lang, ratio = ("nl" if nl >= pl else "pl"), None
    elif total < 15:
        lang, ratio = "unknown", None
    else:
        ratio = de / total
        lang = "de" if ratio >= 0.65 else "en" if ratio <= 0.35 else "mixed"
    return {"lang": lang, "de_ratio": None if ratio is None else round(ratio, 2),
            "english_ok": bool(ENGLISH_OK.search(text or "")), "counted": total}
