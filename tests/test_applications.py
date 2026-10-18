"""Application pipeline: statuses, timeline, reminders, funnel, sync lines and the local server (no network)."""
import json
import os
import shutil
import threading
import unittest
import urllib.error
import urllib.request

from helpers import config

from jobradar import applications, collect, dashboard, feedback, rank, server


def fresh_data_dir():
    d = config.data_dir()
    for name in (config.TRACKER, applications.EVENTS, config.SEEN, config.PREFS):
        p = os.path.join(d, name)
        if os.path.exists(p):
            os.remove(p)


class Pipeline(unittest.TestCase):
    def setUp(self):
        fresh_data_dir()

    def test_status_changes_build_a_timeline(self):
        rows = []
        applications.create(rows, "Acme", "CRM Manager", status="drafted", when="2026-10-01")
        applications.set_status(rows, "acme|crm manager", "applied", when="2026-10-02")
        applications.set_status(rows, "Acme|CRM Manager", "interview", stage="HR screen", when="2026-10-09")
        applications.save(rows)
        rows = applications.load()
        # `date` is when it was sent (the drafted day does not count)
        self.assertEqual((rows[0]["status"], rows[0]["stage"], rows[0]["date"]), ("interview", "HR screen", "2026-10-02"))
        tl = applications.timeline(applications.load_events(), rows[0]["id"])
        self.assertEqual([e["to"] for e in tl], ["drafted", "applied", "interview"])

    def test_vocabulary_and_legacy_spellings(self):
        self.assertEqual(applications.normalize_status("No Response"), "no_response")
        self.assertEqual(applications.normalize_status("offer declined"), "offer_declined")
        with self.assertRaises(ValueError):
            applications.normalize_status("ghosted")

    def test_job_marks_create_and_only_move_forward(self):
        rows, v = [], {"title": "Pricing Analyst", "company": "P", "url": "https://p.example/1"}
        _, msg = applications.upsert_from_job(rows, "https://p.example/1", v, "applied", when="2026-10-01")
        self.assertEqual(msg, "added")
        applications.set_status(rows, rows[0]["id"], "interview", when="2026-10-05")
        _, msg = applications.upsert_from_job(rows, "https://p.example/1", v, "applied", when="2026-10-06")
        self.assertEqual((msg, rows[0]["status"]), ("already tracked", "interview"))

    def test_reached_counts_how_far_it_got(self):
        rows = []
        applications.create(rows, "A", "R1", when="2026-10-01")
        applications.set_status(rows, "a|r1", "interview", when="2026-10-05")
        applications.set_status(rows, "a|r1", "rejected", reason="experience", when="2026-10-12")
        applications.create(rows, "B", "R2", when="2026-10-01")
        rows.append({"id": "c|r3", "company": "C", "role": "R3", "status": "rejected"})  # imported, no history
        events = applications.load_events()
        self.assertEqual([applications.reached(r, events) for r in rows], [2, 1, 1])
        f = applications.funnel(rows, events, profile=config.get())
        self.assertEqual((f["overall"]["applied"], f["overall"]["interview"], f["overall"]["interview_rate"]), (3, 1, 33))
        self.assertEqual(f["median_days_to_reply"], 4)
        self.assertEqual(f["open"], 1)

    def test_reminders(self):
        rows = [
            {"id": "a", "company": "A", "role": "x", "status": "applied", "date": "2026-10-01", "updated": "2026-10-01"},
            {"id": "b", "company": "B", "role": "x", "status": "applied", "date": "2026-09-01", "updated": "2026-09-01"},
            {"id": "c", "company": "C", "role": "x", "status": "interview", "stage": "Round 2", "next_date": "2026-10-17"},
            {"id": "d", "company": "D", "role": "x", "status": "interview", "next_date": "2026-10-10"},
            {"id": "e", "company": "E", "role": "x", "status": "drafted", "next_date": "2026-10-16"},
            {"id": "f", "company": "F", "role": "x", "status": "applied", "date": "2026-10-10", "updated": "2026-10-10"},
        ]
        got = {r["id"]: r["kind"] for r in applications.reminders(rows, [], on="2026-10-15")}
        self.assertEqual(got, {"a": "follow_up", "b": "no_response", "c": "upcoming", "d": "update", "e": "deadline"})


class SyncAndPreferences(unittest.TestCase):
    def setUp(self):
        fresh_data_dir()

    def test_app_sync_lines_and_interviews_lead_the_prompt(self):
        collect.save_seen({"seen": {"https://j.example/1": {"title": "Growth Analyst", "company": "G", "url": "https://j.example/1",
                                                            "status": "ranked", "rank_fit": "high"}}})
        feedback.apply("sync-status: https://j.example/1=applied\n")
        report, prefs = feedback.apply("sync-app: g|growth analyst=interview\nsync-app: nobody|nothing=offer\n")
        self.assertIn("application -> interview", report[0])
        self.assertTrue(report[1].startswith("SKIPPED"))
        self.assertEqual(prefs["interviews"], ["Growth Analyst @ G"])
        self.assertNotIn("Growth Analyst @ G", prefs["liked"])
        prompt = rank.agent_prompt(config.get())
        self.assertLess(prompt.index("led to an interview"), prompt.index("Growth Analyst @ G") + 1)

    def test_payload_links_jobs_and_applications(self):
        collect.save_seen({"seen": {"https://j.example/2": {"title": "Buyer", "company": "B", "url": "https://j.example/2",
                                                            "status": "ranked", "rank_fit": "medium"}}})
        feedback.apply("sync-status: https://j.example/2=applied\n")
        data = dashboard.payload()
        self.assertEqual(data["jobs"][0]["app"], "b|buyer")
        self.assertEqual(data["apps"][0]["fit"], "medium")
        self.assertEqual(data["funnel"]["by"]["fit"][0]["label"], "medium")


class LocalServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_data_dir()
        collect.save_seen({"seen": {"https://j.example/3": {"title": "CRM Manager", "company": "C", "url": "https://j.example/3",
                                                            "status": "ranked", "rank_fit": "high"}}})
        cls.token = "test-token"
        cls.httpd = server.Server(("127.0.0.1", 0), None)
        port = cls.httpd.server_address[1]
        cls.httpd.RequestHandlerClass = server.make_handler(cls.token, port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def post(self, path, body, token=None, host=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Radar-Token": token or self.token})
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_a_taken_port_is_refused(self):
        with self.assertRaises(OSError):
            server.Server(("127.0.0.1", self.httpd.server_address[1]), None)

    def test_page_embeds_the_token(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            page = r.read().decode()
        self.assertIn('const LIVE = "test-token"', page)

    def test_writes_need_token_and_local_host(self):
        self.assertEqual(self.post("/api/job", {"key": "https://j.example/3", "status": "applied"}, token="wrong")[0], 403)
        self.assertEqual(self.post("/api/job", {"key": "x", "status": "applied"}, host="evil.example")[0], 403)

    def test_a_full_round_trip(self):
        status, data = self.post("/api/job", {"key": "https://j.example/3", "status": "applied"})
        self.assertEqual(status, 200)
        self.assertEqual(data["apps"][0]["status"], "applied")
        status, data = self.post("/api/app", {"id": "c|crm manager", "status": "interview",
                                              "fields": {"stage": "Round 1", "next_date": "2026-10-20", "contact": "Kim"}})
        self.assertEqual((status, data["apps"][0]["stage"], data["apps"][0]["contact"]), (200, "Round 1", "Kim"))
        self.assertEqual([e["to"] for e in data["apps"][0]["timeline"]][-1], "interview")
        self.assertEqual(self.post("/api/app", {"id": "c|crm manager", "status": "ghosted"})[0], 400)
        status, data = self.post("/api/app/new", {"company": "Manual Co", "role": "Analyst"})
        self.assertEqual((status, len(data["apps"])), (200, 2))
        self.assertEqual(self.post("/api/app/new", {"company": "Manual Co", "role": "Analyst"})[0], 400)
        self.assertEqual(self.post("/api/nope", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
