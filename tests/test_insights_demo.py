"""Weekly and 7-day stats, conversion and response rates, highlights, and the demo dataset (no network)."""
import datetime
import json
import os
import tempfile
import unittest

from helpers import config

from jobradar import applications, dashboard, demo

ON = "2026-10-20"  # a Tuesday


def app(rows, company, role, applied, path=()):
    applications.create(rows, company, role, status="drafted", when=applied)
    ident = applications.app_id(company, role)
    applications.set_status(rows, ident, "applied", when=applied)
    for status, when in path:
        applications.set_status(rows, ident, status, when=when)


class Stats(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="job-radar-stats-")
        self.old = os.environ.get("JOB_RADAR_DATA")
        os.environ["JOB_RADAR_DATA"] = self.dir

    def tearDown(self):
        os.environ["JOB_RADAR_DATA"] = self.old

    def funnel(self, rows):
        return applications.funnel(rows, applications.load_events(), profile=config.get(), on=ON)

    def test_last_seven_days_against_the_seven_before(self):
        rows = []
        app(rows, "A", "CRM Manager", "2026-10-19", [("interview", "2026-10-20")])
        app(rows, "B", "CRM Specialist", "2026-10-14")
        app(rows, "C", "Brand Manager", "2026-10-13", [("rejected", "2026-10-15")])  # 7 days before
        app(rows, "D", "Buyer", "2026-10-08", [("interview", "2026-10-10")])
        r = self.funnel(rows)["recent"]
        self.assertEqual((r["applied_7d"], r["applied_prev_7d"], r["interviews_7d"], r["interviews_prev_7d"]), (2, 2, 1, 1))

    def test_weekly_buckets_start_on_monday_and_end_this_week(self):
        rows = []
        app(rows, "A", "CRM Manager", "2026-10-19")   # Monday of this week
        app(rows, "B", "Buyer", "2026-10-18", [("interview", "2026-10-21")])  # Sunday, last week; interview this week
        w = self.funnel(rows)["weekly"]
        self.assertEqual(len(w), applications.WEEKS)
        self.assertEqual((w[-1]["week"], w[-1]["applied"], w[-1]["interviews"]), ("2026-10-19", 1, 0))  # 21st is after ON
        self.assertEqual((w[-2]["week"], w[-2]["applied"]), ("2026-10-12", 1))

    def test_rates_and_highlights(self):
        rows = []
        app(rows, "A", "CRM Manager", "2026-10-01", [("interview", "2026-10-05"), ("offer", "2026-10-12")])
        app(rows, "B", "CRM Specialist", "2026-10-01", [("interview", "2026-10-09"), ("rejected", "2026-10-15")])
        app(rows, "C", "Brand Manager", "2026-10-01", [("rejected", "2026-10-03")])
        app(rows, "D", "Buyer", "2026-10-01", [("no_response", "2026-10-30")])  # not a reply
        f = self.funnel(rows)
        self.assertEqual(f["rates"], {"applied_to_interview": 50, "interview_to_offer": 50, "offer_to_hired": 0, "response": 75})
        self.assertEqual(f["highlights"]["top_direction"]["label"], "CRM lifecycle")
        self.assertEqual(f["highlights"]["median_days_to_interview"], 6)
        self.assertEqual(f["median_days_to_reply"], 4)
        self.assertIsNone(f["highlights"]["best_source"])  # no source has 3+ applications with an interview


class Demo(unittest.TestCase):
    def setUp(self):
        self.old = {k: os.environ.get(k) for k in ("JOB_RADAR_DATA", "JOB_RADAR_PROFILE", "JOB_RADAR_DEMO")}

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.reset()

    def test_demo_builds_a_complete_story_relative_to_today(self):
        folder = tempfile.mkdtemp(prefix="job-radar-demo-")
        demo.use_demo_profile()
        demo.build_data(os.path.join(folder, "data"), today=datetime.date(2026, 10, 20))
        data = dashboard.payload()
        self.assertTrue(data["demo"])
        self.assertGreater(len(data["jobs"]), 30)
        f = data["funnel"]
        self.assertGreater(f["overall"]["interview"], 0)
        self.assertGreater(f["overall"]["offer"], 0)
        self.assertGreater(f["recent"]["applied_7d"], 0)
        self.assertGreater(len(data["reminders"]), 3)
        self.assertTrue(f["highlights"]["top_direction"] and f["highlights"]["best_source"])
        statuses = {a["status"] for a in data["apps"]}
        self.assertTrue({"drafted", "applied", "interview", "offer", "rejected"} <= statuses)
        self.assertTrue(all(j["url"].startswith("https://example.com/") for j in data["jobs"]))

    def test_static_page_embeds_demo_data_without_a_token(self):
        folder = tempfile.mkdtemp(prefix="job-radar-demo-")
        demo.use_demo_profile()
        demo.build_data(os.path.join(folder, "data"))
        page = dashboard.render(dashboard.payload())
        self.assertIn("const LIVE = null", page)
        data = json.loads(page.split("let DATA = ")[1].split(";\nconst LIVE")[0])
        self.assertTrue(data["demo"])


if __name__ == "__main__":
    unittest.main()
