"""Template for your own job source. Copy it to sources_custom/<name>.py (no leading "_"),
fill in collect(), add "<name>" to [search] sources in your profile, then try it with

    python radar.py collect --sources <name> --dry-run

Or run /add-source in Claude Code and name the job board: it writes this file and a test for you.

Ground rules: use only public pages or APIs (no login, no CAPTCHA), respect the site's robots.txt
and terms, keep a delay between requests, and call ctx.wanted() before fetching any detail page.
See jobradar/plugins.py for everything `ctx` offers.
"""
NAME = "myboard"
FULL_TEXT = True  # False if you only get a short snippet; such jobs are then verified on the web


def collect(ctx):
    out = []
    for keyword in ctx.keywords:
        # 1. list postings for this keyword, newest first, e.g.
        # data = ctx.http_json(f"https://example.com/api/jobs?q={keyword}&country=de")
        data = {"jobs": []}
        for j in data["jobs"]:
            # 2. skip anything older than ctx.since
            # 3. let Job Radar decide before any further request
            if not ctx.wanted(j["title"], j["company"], j["location"]):
                continue
            # 4. full text: from the listing, or one detail request here
            text = ctx.strip_html(j.get("description", ""))
            out.append(ctx.posting(NAME, j["title"], j["company"], j["location"], j["url"], j.get("date"), text,
                                   snippet=not FULL_TEXT))
        ctx.sleep(1.5)
    return out
