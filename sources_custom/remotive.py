"""Example custom source: Remotive's public remote-jobs API (worldwide, no key needed).

Turn it on by adding "remotive" to [search] sources in your profile. Optional settings:

    [search.sources_config.remotive]
    categories = ["marketing", "sales-business", "data"]   # Remotive category slugs; default: all jobs

Remotive's terms: link back to the Remotive posting and name Remotive as the source (the dashboard
does both), and call the API at most a few times a day; this source makes one request per category
per run. Its robots.txt disallows `search=` URLs, so filtering happens locally through ctx.wanted.
"""
NAME = "remotive"
FULL_TEXT = True  # the API returns the whole description

API = "https://remotive.com/api/remote-jobs"


def collect(ctx):
    categories = ctx.settings.get("categories") or [None]
    out, seen = [], set()
    for category in categories:
        url = API + (f"?category={category}" if category else "")
        jobs = ctx.http_json(url).get("jobs", [])
        for j in jobs:
            if j.get("id") in seen:
                continue
            seen.add(j.get("id"))
            posted = (j.get("publication_date") or "")[:10]
            if posted and posted < ctx.since.isoformat():
                continue
            where = j.get("candidate_required_location") or "Worldwide"
            location = f"Remote ({where})"
            if not ctx.wanted(j.get("title"), j.get("company_name"), location):
                continue
            out.append(ctx.posting(NAME, j.get("title"), j.get("company_name"), location, j.get("url"),
                                   posted or None, ctx.strip_html(j.get("description"))))
        ctx.sleep(2)
    return out
