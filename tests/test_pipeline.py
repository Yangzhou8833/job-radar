"""Collector parsing, gate and store, pre-screen, ranking verdicts and dashboard sync (no network)."""
import datetime
import json
import os
import unittest
from unittest import mock

from helpers import MINIMAL, config, profile_from

from jobradar import collect, dashboard, feedback, prescreen, rank, sources
from jobradar.rules import norm_key

EJ_PAGE = """# 4583 marketing English-speaking jobs in Germany

[### Junior CRM *Marketing* Manager (m/f/d)](/clickout/abc123?ql=q&sig=x&p=1&pg=1)

* Example GmbH
* Berlin
* October 11

You will own our lifecycle campaigns across email and push ...

[### Senior Director *Marketing*](/clickout/def456?ql=q&sig=y&p=2&pg=1)

* Big Corp
* Munich
* October 11

Lead a team of 20 ...

[### Growth Analyst](/clickout/ghi789?ql=q&sig=z&p=3&pg=1)

* Old Startup
* Hamburg
* September 20

An older posting that must be cut off by the date filter ...
"""


class EnglishJobsParser(unittest.TestCase):
    def test_parses_listing_and_respects_date_and_gate(self):
        def fake_get(url, headers=None, **kw):
            return (EJ_PAGE if url.endswith("page=1") else "").encode("utf-8")

        calls = []

        def wanted(title, company, loc):
            calls.append(title)
            return "Senior" not in title

        with mock.patch.object(sources, "http_get", side_effect=fake_get), mock.patch.object(sources.time, "sleep"):
            out = sources.englishjobs(datetime.date(2026, 10, 10), ["marketing"], wanted,
                                      today=datetime.date(2026, 10, 12), log=lambda m: None)
        self.assertEqual([p["title"] for p in out], ["Junior CRM Marketing Manager (m/f/d)"])
        self.assertEqual((out[0]["company"], out[0]["location"], out[0]["posted_date"]), ("Example GmbH", "Berlin", "2026-10-11"))
        self.assertTrue(out[0]["text_is_snippet"])
        self.assertNotIn("Growth Analyst", calls)

    def test_listing_date_from_last_year(self):
        self.assertEqual(sources._ej_date("December 30", datetime.date(2027, 1, 2)), datetime.date(2026, 12, 30))


class ArbeitnowCountrySites(unittest.TestCase):
    def test_country_site_domain_becomes_part_of_the_location(self):
        page = {"data": [
            {"title": "Trainee E-Commerce", "company_name": "X", "location": "Horn", "created_at": 1_900_000_000,
             "url": "https://www.arbeitnow.ch/jobs/companies/x/trainee-1", "description": "d"},
            {"title": "Graduate Analyst", "company_name": "Y", "location": "Cheltenham", "created_at": 1_900_000_000,
             "url": "https://www.arbeitnow.co.uk/jobs/companies/y/graduate-2", "description": "d"},
            {"title": "Junior Analyst", "company_name": "Z", "location": "Berlin", "created_at": 1_900_000_000,
             "url": "https://www.arbeitnow.com/jobs/companies/z/junior-3", "description": "d"}]}
        locs = []
        with mock.patch.object(sources, "http_json", side_effect=[page, {"data": []}]), mock.patch.object(sources.time, "sleep"):
            sources.arbeitnow(datetime.date(2026, 1, 1), lambda t, c, l: locs.append(l) or True, log=lambda m: None)
        self.assertEqual(locs, ["Horn, Switzerland", "Cheltenham, United Kingdom", "Berlin"])
        self.assertEqual([config.get().country_of(l) for l in locs], [None, None, "DE"])


class GateAndStore(unittest.TestCase):
    def test_gate_rules_and_cross_source_dedupe(self):
        gate = collect.Gate(set(), {norm_key("Taktile", "Strategy & Operations Associate")}, config.get())
        self.assertFalse(gate("Strategy & Operations Associate (m/f/d)", "TAKTILE", "Berlin"))  # known
        self.assertFalse(gate("Revenue Operations Associate", "Ben", "London"))                 # out of scope
        self.assertFalse(gate("Marketing Intern", "X", "Amsterdam, Netherlands"))               # internship abroad
        self.assertTrue(gate("Junior Pricing Analyst", "Y", "Vienna, Austria"))                  # full-time abroad
        self.assertFalse(gate("Senior Growth Manager", "X", "Berlin"))
        self.assertFalse(gate("Werkstudent Marketing", "X", "Berlin"))
        self.assertTrue(gate("Junior CRM Manager", "Example GmbH", "Berlin"))
        self.assertFalse(gate("Junior CRM Manager (m/w/d)", "Example GmbH", "Berlin, Germany"))  # second source
        self.assertEqual(gate.counts["passed"], 2)

    def test_store_keys_and_snippet_flag(self):
        seen = {}
        postings = [
            sources.posting("arbeitnow", "Junior CRM Manager", "Example GmbH", "Berlin", "https://a.example/x", "2026-10-11", "Full text"),
            sources.posting("englishjobs", "Growth Analyst", "Y", "Munich", "https://englishjobs.de/clickout/abc?sig=1",
                            "2026-10-11", "snippet", snippet=True),
            sources.posting("workable", "Known Job", "Q", "Berlin", "https://known.example/job", "2026-10-11", "t"),
        ]
        added = collect.store(seen, postings, "2026-10-12", dry_run=True, known_urls={"https://known.example/job"})
        self.assertEqual(added, 2)
        self.assertEqual(seen["https://a.example/x"]["status"], "new")
        self.assertTrue(seen["englishjobs:" + norm_key("Y", "Growth Analyst")]["jd_snippet_only"])


class LinkedInPlan(unittest.TestCase):
    def test_daily_terms_every_day_and_rotating_halves(self):
        cfg = {"daily_terms": ["junior"], "rotating_terms": ["a", "b", "c", "d"]}
        self.assertEqual(rank_keys(sources.linkedin_plan(cfg, 2)), {"junior": 1, "a": 2, "c": 2})
        self.assertEqual(rank_keys(sources.linkedin_plan(cfg, 3)), {"junior": 1, "b": 2, "d": 2})

    def test_city_topup_only_when_cut_off(self):
        cfg = {"location": "Germany", "city_topup": ["Berlin, Germany"], "max_pages": 2, "delay_seconds": 0,
               "daily_terms": ["graduate programme", "CRM manager"]}
        calls = []

        def fake_run(cmd, **kw):
            term, loc = cmd[cmd.index("-q") + 1], cmd[cmd.index("-l") + 1]
            calls.append((term, loc))
            n = 10 if term == "CRM manager" and loc == "Germany" else 3
            res = [{"id": f"{term}{loc}{len(calls)}{i}", "title": "CRM Manager", "company": f"C{i}", "location": "Berlin",
                    "url": f"https://de.linkedin.com/jobs/view/{i}?x"} for i in range(n)]
            return mock.Mock(returncode=0, stdout=json.dumps({"results": res}))

        with mock.patch.object(sources.time, "sleep"):
            sources.linkedin(cfg, lambda *a: True, ".", day_of_year=2, log=lambda m: None, run=fake_run)
        self.assertIn(("CRM manager", "Berlin, Germany"), calls)
        self.assertNotIn(("graduate programme", "Berlin, Germany"), calls)


def rank_keys(plan):
    return dict(plan)


def write_cache(name, text):
    os.makedirs(config.data(config.JD_CACHE), exist_ok=True)
    with open(config.data(config.JD_CACHE, name), "w", encoding="utf-8") as f:
        f.write(text)
    return name


EN_JD = ("Your tasks: plan CRM campaigns and analyse results. Your profile: degree in marketing, first experience "
         "through internships, very good English. We offer a friendly team in Berlin and you will work with our CRM tools.")


class Prescreen(unittest.TestCase):
    def entry(self, title, text, location="Berlin"):
        return {"title": title, "company": "Example", "location": location, "status": "new", "portal": "arbeitnow",
                "jd_cache": write_cache(f"{abs(hash(title + text))}.txt", text)}

    def run_one(self, v, profile=None):
        data = {"seen": {"k": v}}
        prescreen.run(data, profile or config.get())
        return data["seen"]["k"]

    def test_keeps_a_fitting_english_posting(self):
        v = self.run_one(self.entry("Junior CRM Manager", EN_JD))
        self.assertEqual(v["status"], "new")
        self.assertEqual(v["country"], "DE")

    def test_skips_years_and_fluent_german(self):
        self.assertEqual(self.run_one(self.entry("CRM Manager", EN_JD + " You bring 5+ years of experience in CRM."))["status"], "skipped")
        v = self.run_one(self.entry("CRM Manager", EN_JD + " Fluent German and English required."))
        self.assertEqual((v["status"], v["language_gate"]), ("skipped", "FAIL"))

    def test_german_c1_profile_has_no_german_gate(self):
        p = profile_from(MINIMAL.format(stage="graduate", german="C1").replace('"brand"]', '"brand", "crm"]'))
        v = self.run_one(self.entry("CRM Manager", EN_JD + " Fluent German and English required."), p)
        self.assertEqual(v["status"], "new")

    def test_internship_requiring_enrollment_is_skipped_for_graduates_only(self):
        text = EN_JD + " You must be enrolled at a university for the whole internship."
        self.assertEqual(self.run_one(self.entry("Marketing Intern", text))["internship_gate"], "FAIL")
        student = profile_from(MINIMAL.format(stage="student", german="B1"))
        self.assertEqual(self.run_one(self.entry("Marketing Intern", text), student)["status"], "new")


class Verdicts(unittest.TestCase):
    def test_gates_and_caveats(self):
        today = "2026-10-12"
        v = {}
        self.assertEqual(rank.verdict_to_entry(v, {"key": "k", "experience_gate": "FAIL_CLEAR", "fit": None}, today)["rank_fit"], "excluded")
        self.assertEqual(rank.verdict_to_entry(v, {"key": "k", "experience_gate": "PASS", "language_gate": "PASS", "fit": "high"}, today)["rank_fit"], "high")
        amb = rank.verdict_to_entry(v, {"key": "k", "experience_gate": "FAIL_AMBIGUOUS", "language_gate": "PASS", "fit": "medium"}, today)
        self.assertEqual(amb["rank_fit"], "excluded")
        de = rank.verdict_to_entry({"language_flag": "DE_JD"}, {"key": "k", "experience_gate": "PASS", "language_gate": "PASS", "fit": "high"}, today)
        self.assertEqual(de["rank_fit"], "high")
        lang = rank.verdict_to_entry(v, {"key": "k", "experience_gate": "PASS", "language_gate": "FAIL", "fit": "high"}, today)
        self.assertEqual(lang["rank_fit"], "excluded")
        snip = rank.verdict_to_entry({"jd_snippet_only": True}, {"key": "k", "experience_gate": "PASS", "language_gate": "PASS", "fit": "medium", "note": "fits"}, today)
        self.assertTrue(snip["rank_reason"].startswith(rank.SNIPPET_NOTE))

    def test_excerpt_keeps_requirements_and_language_lines(self):
        text = "About us: " + "x " * 900 + "\nYour tasks: run campaigns.\nYour profile: SQL and Excel.\n" + "y " * 50
        text = "Fluent German required.\n" + text
        out = rank.excerpt(text)
        self.assertIn("Your profile: SQL", out)
        self.assertIn("Fluent German required", out)
        noisy = rank.excerpt("Find Jobs in Germany on Arbeitnow\n" + "z " * 2000 + text)
        self.assertNotIn("Arbeitnow", noisy.split("Language lines:")[-1])

    def test_batch_count_stays_under_the_agent_limit(self):
        self.assertEqual(rank.batch_size_for(100, 25), 25)
        self.assertEqual(-(-1000 // rank.batch_size_for(1000, 25)) <= rank.MAX_BATCHES, True)


class DashboardAndSync(unittest.TestCase):
    def test_sync_lines_update_status_tracker_and_preferences(self):
        data = {"seen": {
            "https://a.example/job?id=1": {"title": "CRM Manager", "company": "A", "url": "https://a.example/job?id=1",
                                           "status": "ranked", "rank_fit": "high", "first_seen": "2026-10-12"},
            "https://b.example/2": {"title": "Buyer", "company": "B", "url": "https://b.example/2", "status": "ranked",
                                    "rank_fit": "medium", "first_seen": "2026-10-12"}}}
        collect.save_seen(data)
        report, prefs = feedback.apply("sync-status: https://a.example/job?id=1=applied\n"
                                       "sync-delete: https://b.example/2=too much travel\n")
        self.assertEqual(len(report), 2)
        seen = collect.load_seen()["seen"]
        self.assertEqual(seen["https://a.example/job?id=1"]["apply_status"], "applied")
        self.assertEqual(seen["https://b.example/2"]["user_feedback"], "not_interested")
        self.assertIn("CRM Manager @ A", prefs["liked"])
        self.assertTrue(any("too much travel" in x for x in prefs["not_interested"]))
        with open(config.data(config.TRACKER), encoding="utf-8") as f:
            self.assertIn("CRM Manager", f.read())
        self.assertTrue(any("application added" in line for line in report))
        path = dashboard.build(os.path.join(config.data_dir(), "dash.html"))
        html = open(path, encoding="utf-8").read()
        jobs = json.loads(html.split("let DATA = ")[1].split(";\nconst LIVE")[0])["jobs"]
        self.assertEqual([j["title"] for j in jobs], ["CRM Manager"])  # deleted jobs leave the page

    def test_preferences_reach_the_prompt(self):
        feedback.build_prefs({"x": {"title": "Pricing Analyst", "company": "P", "apply_status": "ready_to_apply_manually"}})
        self.assertIn("Pricing Analyst @ P", rank.agent_prompt(config.get()))


if __name__ == "__main__":
    unittest.main()
