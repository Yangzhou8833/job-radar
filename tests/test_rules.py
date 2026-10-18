"""Title, location, years, language and internship rules (no network)."""
import unittest

from helpers import MINIMAL, config, profile_from

from jobradar import countries
from jobradar.jd_language import detect
from jobradar.rules import (INTERN_HARD_BLOCK, SOFT_GERMAN, WORK_PERMIT_REQUIRED, enrollment_required, german_required,
                            internship_unconfirmed, title_is_senior, title_rejection, years_requirement)

DE = ("Für unser Team in Hamburg suchen wir dich als Brand Manager. Du bist verantwortlich für die "
      "Entwicklung der Marke und arbeitest eng mit dem Vertrieb zusammen. Wir bieten dir ein "
      "spannendes Umfeld und eine attraktive Vergütung. Du hast sehr gute Deutschkenntnisse und bist "
      "ein Teamplayer mit Erfahrung im Marketing.")
EN = ("We are looking for a Brand Manager to join our team in Hamburg. You will be responsible for "
      "developing the brand and work closely with the sales team. We offer an exciting environment "
      "and you have experience in marketing and are a team player with strong analytical skills.")


class Keywords(unittest.TestCase):
    def test_whole_words_prefixes_and_regex(self):
        rx = config.keywords_regex(["crm", "analy*", "e-commerce", "founder's associate", r"re:\bsea\b"])
        for t in ["CRM Manager", "Data Analyst", "Analytics Lead", "E-Commerce Manager", "Founder's Associate", "SEA Manager"]:
            self.assertTrue(rx.search(t), t)
        for t in ["Scrum Master", "Research Assistant", "Seasonal Worker"]:
            self.assertFalse(rx.search(t), t)

    def test_multi_word_keyword_tolerates_extra_spaces(self):
        self.assertTrue(config.keywords_regex(["email marketing"]).search("Email  Marketing Manager"))


class Titles(unittest.TestCase):
    def setUp(self):
        self.p = config.get()

    def test_senior_titles(self):
        for t in ["Senior Marketing Analyst", "Head of Brand", "Teamleiter Vertrieb (m/w/d)", "Marketing Lead DACH",
                  "Head (f/m/d) of Service Operations Controlling", "Experienced Business Controller (f/m/d)",
                  "Customer Success Leader, Southern Europe & DACH"]:
            self.assertTrue(title_is_senior(t), t)
        for t in ["(Senior) Marketing Analyst (m/w/d)", "Junior Brand Manager", "Lead Generation Specialist",
                  "Brand Manager (m/w/d)"]:
            self.assertFalse(title_is_senior(t), t)

    def test_title_rejections_follow_the_profile(self):
        cases = {
            "Werkstudent Marketing (m/w/d)": "other track (Werkstudent / Ausbildung / thesis / freelance)",
            "Marketing Manager (f/m/d) - Mandatory 6 Month Unpaid Internship": "mandatory or unpaid internship",
            "Warehouse employee - Amazon": "non-office or gig-work title",
            "Consumer Insights Specialist - Fully Remote | Upto $120/hr": "non-office or gig-work title",
            "Enterprise Account Executive - DACH": "senior sales title",
            "Software Engineer (Kotlin)": "title outside your directions",
            "Brandschutzbeauftragter (m/w/d)": "title outside your directions",
        }
        for title, reason in cases.items():
            self.assertEqual(title_rejection(title, self.p), reason, title)
        for title in ["Junior Brand Manager (m/w/d)", "Sales Operations Analyst", "Junior Einkäufer (m/w/d)",
                      "CRM Manager", "Business Controller", "Spanish Speaking Account Manager", "Product Marketing Manager"]:
            self.assertIsNone(title_rejection(title, self.p), title)

    def test_students_keep_working_student_jobs(self):
        student = profile_from(MINIMAL.format(stage="student", german="B1"))
        self.assertIsNone(title_rejection("Werkstudent Marketing (m/w/d)", student))
        graduate = profile_from(MINIMAL.format(stage="graduate", german="B1"))
        self.assertIsNotNone(title_rejection("Werkstudent Marketing (m/w/d)", graduate))


class Locations(unittest.TestCase):
    def test_country_of_with_scope_order_and_unknowns(self):
        scope = ["DE", "NL", "AT"]
        cases = {"Munich, Bavaria, Germany": "DE", "Amsterdam, North Holland, Netherlands": "NL", "Wien": "AT",
                 "Remote": "DE", "": "DE", "Hamburg or Amsterdam": "DE", "Berlin, DE": "DE", "UK: London": None,
                 "Shanghai, China": None, "Barcelona": None, "Warsaw, Poland": None, "Rio de Janeiro": None,
                 "Leinfelden-Echterdingen": "DE"}
        for loc, code in cases.items():
            self.assertEqual(countries.country_of(loc, scope, "DE"), code, loc)

    def test_strict_and_out_of_scope_unknowns(self):
        self.assertIsNone(countries.country_of("Remote", ["DE"], "DE", strict=True))
        self.assertIsNone(countries.country_of("Somewhere", ["DE"], ""))
        self.assertEqual(countries.country_of("Paris, France", ["FR", "DE"], "DE"), "FR")


class Years(unittest.TestCase):
    def test_years_requirement(self):
        self.assertEqual(years_requirement("You bring 5+ years of experience in FMCG.")[0], 5)
        self.assertEqual(years_requirement("Mindestens 3 Jahre relevante Berufserfahrung")[0], 3)
        self.assertEqual(years_requirement("Du hast mehrjährige Berufserfahrung im Marketing.")[0], 3)
        self.assertEqual(years_requirement("3+ years in Customer Success")[0], 3)
        self.assertEqual(years_requirement("A minimum of three years' experience in project management")[0], 3)
        self.assertIsNone(years_requirement("First experience through internships is a plus.")[0])

    def test_years_false_positives(self):
        self.assertNotEqual(years_requirement("1–3+ years of hands-on experience in HR Operations")[0], 3)
        self.assertIsNone(years_requirement("Das macht uns besonders: 4+ Jahre Hypergrowth (von 10 auf 110 Mitarbeitende)")[0])
        self.assertIsNone(years_requirement("a global career after approximately 3-4 years in the Strategy Team.")[0])


class Languages(unittest.TestCase):
    def test_detection(self):
        self.assertEqual(detect(DE)["lang"], "de")
        self.assertEqual(detect(EN)["lang"], "en")
        self.assertEqual(detect("Brand Manager (m/w/d)")["lang"], "unknown")
        self.assertTrue(detect(DE + " Unsere Arbeitssprache ist Englisch.")["english_ok"])

    def test_german_required_and_soft_german(self):
        for t in ["Fluent German and English required", "German C1 required", "Sehr gute Deutschkenntnisse",
                  "Deutsch fließend (C1)", "verhandlungssichere Deutschkenntnisse"]:
            self.assertTrue(german_required(t), t)
        for t in ["German is a plus", "Gute Deutschkenntnisse (B2) und sehr gute Englischkenntnisse", EN]:
            self.assertFalse(german_required(t), t)
        self.assertTrue(SOFT_GERMAN.search("Deutschkenntnisse auf Niveau B1"))
        self.assertFalse(SOFT_GERMAN.search("Englischkenntnisse von Vorteil"))

    def test_german_gate_depends_on_level(self):
        self.assertTrue(profile_from(MINIMAL.format(stage="graduate", german="B1")).german_gate)
        self.assertFalse(profile_from(MINIMAL.format(stage="graduate", german="C1")).german_gate)


class InternshipsAndPermits(unittest.TestCase):
    def test_enrollment_and_graduate_confirmation(self):
        self.assertTrue(enrollment_required("Praktikum Marketing (m/w/d)", "Du bist eingeschriebene/r Student/in."))
        self.assertIsNone(enrollment_required("Marketing Intern", "Current students or recent graduates are welcome."))
        self.assertFalse(internship_unconfirmed("Intern New Markets", "Recent graduates are welcome to apply."))
        self.assertTrue(internship_unconfirmed("Strategy Intern", "Open to undergraduate and graduate students."))
        self.assertTrue(INTERN_HARD_BLOCK.search("This is a Pflichtpraktikum."))

    def test_work_permit(self):
        for t in ["You must have a valid work permit for the Netherlands.", "We are unable to offer visa sponsorship.",
                  "EU citizenship required."]:
            self.assertTrue(WORK_PERMIT_REQUIRED.search(t), t)
        self.assertFalse(WORK_PERMIT_REQUIRED.search("We offer visa sponsorship and relocation support."))


class ProfileValidation(unittest.TestCase):
    def test_bad_values_are_explained(self):
        with self.assertRaises(SystemExit):
            profile_from(MINIMAL.format(stage="retired", german="B1"))
        with self.assertRaises(SystemExit):
            profile_from(MINIMAL.format(stage="graduate", german="fluent"))
        with self.assertRaises(SystemExit):
            profile_from(MINIMAL.format(stage="graduate", german="B1").replace('["DE"]', '["XX"]'))


if __name__ == "__main__":
    unittest.main()
