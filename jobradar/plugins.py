"""Your own job sources: one Python file in sources_custom/ per source.

A source file needs three things:

    NAME = "myboard"      # the name you put in [search] sources, and the dashboard's source label
    FULL_TEXT = True      # True if collect() returns the full posting text, False for a short snippet
    def collect(ctx):     # returns a list of ctx.posting(...) dicts
        ...

`ctx` gives the source everything it needs, so it never has to import the rest of Job Radar:

    ctx.since           date: keep postings published on or after it
    ctx.days            the same window in days
    ctx.keywords        your [search] keywords
    ctx.countries       your country codes, ctx.country_names their names ("Germany", ...)
    ctx.settings        this source's own table from the profile, [search.sources_config.<NAME>]
    ctx.wanted(title, company, location) -> bool
                        call it BEFORE fetching a posting's detail page; it applies dedupe, your
                        countries, directions and title rules, so skipped postings cost no requests
    ctx.posting(source, title, company, location, url, posted_date, text, snippet=False)
    ctx.http_get(url) / ctx.http_json(url)   polite GET with backoff on HTTP 429
    ctx.strip_html(html), ctx.sleep(seconds), ctx.log(message)

Files whose name starts with "_" are ignored (use that for templates). A source only runs when
its NAME is listed in [search] sources. A source that fails is logged and the others go on.
See sources_custom/remotive.py for a complete example and /add-source to have Claude Code write
one for a job board you name.
"""
import datetime
import importlib.util
import os
import time
import types

from . import config, countries, sources

PLUGIN_DIR = os.path.join(config.ROOT, "sources_custom")
REQUIRED = ("NAME", "collect")


def discover(folder=None):
    """{NAME: module} for every valid source file in sources_custom/."""
    folder = folder or PLUGIN_DIR
    found = {}
    if not os.path.isdir(folder):
        return found
    for fname in sorted(os.listdir(folder)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(folder, fname)
        spec = importlib.util.spec_from_file_location(f"jobradar_source_{fname[:-3]}", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:  # a broken plugin must not stop the built-in sources
            print(f"{os.path.basename(folder)}/{fname}: not loaded ({type(e).__name__}: {e})")
            continue
        if not all(hasattr(module, attr) for attr in REQUIRED):
            print(f"{os.path.basename(folder)}/{fname}: not loaded (needs NAME and collect(ctx))")
            continue
        found[module.NAME] = module
    return found


def context(profile, since, wanted, log, name=""):
    settings = profile.search.get("sources_config", {}).get(name, {})
    return types.SimpleNamespace(
        since=since, days=max(1, (datetime.date.today() - since).days),
        keywords=profile.search.get("keywords", []), countries=list(profile.countries),
        country_names=[countries.workable_name(c) for c in profile.countries], settings=settings,
        wanted=wanted, posting=sources.posting, http_get=sources.http_get, http_json=sources.http_json,
        strip_html=sources.strip_html, sleep=time.sleep, log=log, profile=profile)
