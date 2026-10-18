"""Custom sources (sources_custom/) and company boards from the profile (no network)."""
import datetime
import os
import tempfile
import textwrap
import types
import unittest
from unittest import mock

from helpers import ROOT, config, profile_from, MINIMAL

from jobradar import ats_feeds, collect, plugins, sources


def fake_ctx(**over):
    ctx = dict(since=datetime.date(2026, 10, 10), days=2, keywords=["marketing"], countries=["DE"],
               country_names=["Germany"], settings={}, wanted=lambda *a: True, posting=sources.posting,
               http_get=None, http_json=None, strip_html=sources.strip_html, sleep=lambda s: None,
               log=lambda m: None, profile=config.get())
    ctx.update(over)
    return types.SimpleNamespace(**ctx)


class Discovery(unittest.TestCase):
    def test_bundled_example_loads_and_template_is_ignored(self):
        found = plugins.discover()
        self.assertIn("remotive", found)
        self.assertNotIn("myboard", found)  # _template.py starts with "_"

    def test_broken_or_incomplete_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "good.py"), "w").write("NAME = 'good'\nFULL_TEXT = False\ndef collect(ctx):\n    return []\n")
            open(os.path.join(d, "broken.py"), "w").write("this is not python")
            open(os.path.join(d, "noname.py"), "w").write("def collect(ctx):\n    return []\n")
            found = plugins.discover(d)
        self.assertEqual(list(found), ["good"])

    def test_custom_sources_slot_in_by_full_text_flag(self):
        full = types.SimpleNamespace(NAME="full", FULL_TEXT=True)
        snip = types.SimpleNamespace(NAME="snip", FULL_TEXT=False)
        order, _ = collect.available_sources({"full": full, "snip": snip})
        self.assertLess(order.index("full"), order.index("linkedin"))
        self.assertGreater(order.index("snip"), order.index("linkedin"))
        self.assertEqual(order[-1], "englishjobs")

    def test_unknown_source_names_are_reported(self):
        p = profile_from(MINIMAL.format(stage="graduate", german="B1") + '\n[search]\nsources = ["arbeitnow", "nosuch"]\n')
        msgs = []
        chosen, _ = collect.chosen_sources(p, log=msgs.append, custom={})
        self.assertEqual(chosen, ["arbeitnow"])
        self.assertTrue(any("nosuch" in m for m in msgs))


class CustomSourceRun(unittest.TestCase):
    def test_collect_source_runs_a_plugin_and_marks_snippets(self):
        mod = types.SimpleNamespace(NAME="snip", FULL_TEXT=False, collect=lambda ctx: [
            ctx.posting("snip", "Marketing Analyst", "A", "Berlin", "https://x.example/1", "2026-10-11", "short")])
        out = collect.collect_source("snip", config.get(), datetime.date(2026, 10, 10), lambda *a: True,
                                     lambda m: None, custom={"snip": mod})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "snip")
        seen = {}
        collect.store(seen, out, "2026-10-12", dry_run=True)
        self.assertTrue(seen["https://x.example/1"].get("jd_snippet_only") is None)  # snippet flag needs text_is_snippet
        out[0]["text_is_snippet"] = True
        seen = {}
        collect.store(seen, out, "2026-10-12", dry_run=True)
        self.assertTrue(seen["https://x.example/1"]["jd_snippet_only"])

    def test_remotive_example_filters_by_date_and_gate(self):
        remotive = plugins.discover()["remotive"]
        payload = {"jobs": [
            {"id": 1, "title": "Growth Marketing Manager", "company_name": "A", "url": "https://remotive.com/remote-jobs/1",
             "publication_date": "2026-10-12T10:00:00", "candidate_required_location": "Europe", "description": "<p>Own growth</p>"},
            {"id": 2, "title": "Old Marketing Job", "company_name": "B", "url": "https://remotive.com/remote-jobs/2",
             "publication_date": "2026-09-01T10:00:00", "candidate_required_location": "Worldwide", "description": "x"},
            {"id": 3, "title": "Senior Engineer", "company_name": "C", "url": "https://remotive.com/remote-jobs/3",
             "publication_date": "2026-10-12T10:00:00", "candidate_required_location": "USA", "description": "x"}]}
        calls = []
        out = remotive.collect(fake_ctx(http_json=lambda url: calls.append(url) or payload,
                                        wanted=lambda t, c, l: "Senior" not in t))
        self.assertEqual([p["title"] for p in out], ["Growth Marketing Manager"])
        self.assertEqual(out[0]["location"], "Remote (Europe)")
        self.assertEqual(out[0]["text"].strip(), "Own growth")
        self.assertEqual(calls, ["https://remotive.com/api/remote-jobs"])  # one request, no search= (robots.txt)


class CompanyBoards(unittest.TestCase):
    def test_profile_boards_are_added_once_and_bad_entries_reported(self):
        p = profile_from(MINIMAL.format(stage="graduate", german="B1")
                         + '\n[search]\ncompany_boards = ["greenhouse:stripe", "Lever:Spotify", "nosystem:x", "ashby"]\n')
        reg, msgs = {"boards": {}, "probed": {}}, []
        self.assertEqual(ats_feeds.seed_from_profile(reg, p, log=msgs.append), 2)
        self.assertEqual(sorted(reg["boards"]), ["greenhouse:stripe", "lever:spotify"])
        self.assertEqual(ats_feeds.seed_from_profile(reg, p, log=msgs.append), 0)
        self.assertEqual(len([m for m in msgs if "ignored" in m]), 4)


if __name__ == "__main__":
    unittest.main()
