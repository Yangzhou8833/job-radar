"""`python radar.py demo`: the full dashboard on made-up data, for a first look or a live demo.

    python radar.py demo                # fresh demo data, opens the live dashboard (Ctrl+C to stop)
    python radar.py demo --static PATH  # write a self-contained demo page instead (no server)

The demo uses the example profile (Alex Example) and about 45 jobs and 24 applications at
fictional companies, with dates relative to today so "last 7 days", reminders and the weekly
chart always look current. It lives in demo/data (git-ignored) and is rebuilt on every start,
so clicking around never touches your own profile or data. No network, no Claude account.
"""
import datetime
import os
import shutil

from . import applications, config
from .collect import save_seen

DEMO_DIR = os.path.join(config.ROOT, "demo", "data")
URL = "https://example.com/jobs/"

# title, company, location, country, source, fit, reason, days since posted, found today?
JOBS = [
    ("CRM Manager (m/f/d)", "Lumen Foods", "Hamburg", "DE", "ats:personio", "high", "Lifecycle campaigns plus Excel and Power BI reporting, FMCG", 1, True),
    ("Junior Brand Manager", "Nordlicht Beauty", "Hamburg", "DE", "bundesagentur", "high", "Brand activation across markets, matches consumer goods background", 2, True),
    ("Marketing Analyst", "Copperleaf Commerce", "Berlin", "DE", "ats:greenhouse", "high", "GA4, SQL and dashboarding are the core of the role", 1, True),
    ("Growth Marketing Associate", "Vela Mobility", "Berlin", "DE", "ats:ashby", "high", "Paid social and A/B testing, English-speaking team", 3, False),
    ("Commercial Analyst - DACH", "Riverstone Foods", "Munich", "DE", "linkedin-search", "high", "Sales and channel analysis for retail accounts", 2, True),
    ("E-commerce Manager Marketplaces", "Oakline Retail", "Cologne", "DE", "arbeitnow", "high", "Amazon and marketplace growth, KPI ownership", 4, False),
    ("Product Marketing Associate", "Juniper Payments", "Amsterdam", "NL", "workable", "high", "Go-to-market for new markets; visa sponsorship offered", 2, True),
    ("Graduate Programme Marketing & Sales", "Fernhill Pharma", "Frankfurt", "DE", "bundesagentur", "high", "Rotations in brand and sales, graduates welcome", 5, False),
    ("Pricing Analyst", "Quayside Logistics", "Hamburg", "DE", "ats:personio", "high", "Pricing models in Excel, commercial stakeholders", 3, False),
    ("Spanish-speaking Account Manager", "Glimmer Cosmetics", "Berlin", "DE", "englishjobs", "high", "Snippet only: open the original posting; Spanish market focus", 1, True),
    ("Junior Category Manager", "Brightwave Retail", "Düsseldorf", "DE", "linkedin-search", "medium", "Assortment work is adjacent; German is a plus only", 2, False),
    ("Customer Success Associate", "Halden Analytics", "Berlin", "DE", "ats:ashby", "medium", "SaaS onboarding; analytics skills help", 4, False),
    ("Campaign Manager", "Pinecrest Media", "Hamburg", "DE", "arbeitnow", "medium", "Campaign planning fits, media agency setting", 6, False),
    ("Business Development Associate", "Tidewater Energy", "Essen", "DE", "bundesagentur", "medium", "B2B energy sales, partly adjacent", 3, False),
    ("Supply Chain Analyst", "Quayside Logistics", "Bremen", "DE", "ats:personio", "medium", "Planning and reporting, less marketing", 5, False),
    ("Sales Operations Specialist", "Alder Bank", "Vienna", "AT", "workable", "medium", "CRM hygiene and reporting; banking is new", 2, True),
    ("Marketing Coordinator EMEA", "Kestrel Health", "Amsterdam", "NL", "linkedin-search", "medium", "Event and campaign coordination", 7, False),
    ("Trade Marketing Specialist", "Riverstone Foods", "Munich", "DE", "linkedin-search", "medium", "Shopper marketing in retail, German B2 asked", 4, False),
    ("Junior Product Owner", "Copperleaf Commerce", "Berlin", "DE", "ats:greenhouse", "medium", "Product work is a stretch but data-heavy", 3, False),
    ("Content Marketing Manager", "Sablewood", "Leipzig", "DE", "arbeitnow", "medium", "Content plans and SEO; writing focus", 8, False),
    ("Business Analyst Sales", "Marlow & Finch", "Frankfurt", "DE", "bundesagentur", "medium", "Sales reporting, SQL", 6, False),
    ("Social Media Manager", "Orbit Travel", "Berlin", "DE", "englishjobs", "medium", "Snippet only: open the original posting", 2, False),
    ("Procurement Analyst", "Tidewater Energy", "Essen", "DE", "ats:smartrecruiters", "medium", "Spend analysis in Excel", 5, False),
    ("Retention Marketing Analyst", "Vela Mobility", "Berlin", "DE", "ats:ashby", "medium", "Cohort analysis, CRM tools", 1, True),
    ("Office Marketing Assistant", "Pinecrest Media", "Hamburg", "DE", "bundesagentur", "low", "Mostly admin tasks", 3, False),
    ("Data Engineer", "Halden Analytics", "Berlin", "DE", "ats:ashby", "low", "Engineering role, not marketing analytics", 2, False),
    ("Field Sales Representative", "Oakline Retail", "Stuttgart", "DE", "arbeitnow", "low", "Field sales with car, off direction", 5, False),
    ("PR Specialist", "Sablewood", "Leipzig", "DE", "linkedin-search", "low", "Press relations, little data work", 7, False),
    ("Logistics Coordinator", "Quayside Logistics", "Hamburg", "DE", "bundesagentur", "low", "Operations scheduling", 4, False),
    ("Marketing Intern (6 months)", "Glimmer Cosmetics", "Berlin", "DE", "ats:personio", "low", "Check: are graduates eligible?; internship level", 2, False),
    ("Sales Assistant", "Brightwave Retail", "Düsseldorf", "DE", "bundesagentur", "low", "Back-office sales support", 6, False),
    ("Senior CRM Manager", "Lumen Foods", "Hamburg", "DE", "linkedin-search", "excluded", "", 2, True),
    ("Head of Growth", "Juniper Payments", "Amsterdam", "NL", "workable", "excluded", "", 3, False),
    ("Brand Manager (m/w/d)", "Fernhill Pharma", "Frankfurt", "DE", "bundesagentur", "excluded", "", 1, True),
    ("Key Account Manager Retail", "Riverstone Foods", "Munich", "DE", "linkedin-search", "excluded", "", 4, False),
    ("Marketing Manager DACH", "Kestrel Health", "Vienna", "AT", "workable", "excluded", "", 5, False),
    ("Performance Marketing Lead", "Copperleaf Commerce", "Berlin", "DE", "ats:greenhouse", "excluded", "", 2, False),
]
EXCLUDE_NOTES = {
    "Senior CRM Manager": ("experience_gate", "FAIL_CLEAR", "experience_note", "senior title, 5+ years required"),
    "Head of Growth": ("experience_gate", "FAIL_CLEAR", "experience_note", "leads a team of eight"),
    "Brand Manager (m/w/d)": ("language_gate", "FAIL", "language_note", "verhandlungssichere Deutschkenntnisse required"),
    "Key Account Manager Retail": ("language_gate", "FAIL", "language_note", "fluent German for retail buyers"),
    "Marketing Manager DACH": ("work_auth_gate", "FAIL", "work_auth_note", "requires an existing Austrian work permit"),
    "Performance Marketing Lead": ("experience_gate", "FAIL_CLEAR", "experience_note", "4+ years in paid media"),
}

# company, role, source, fit, country, applied N days ago, then the path as (status, days after applying, stage)
APPS = [
    ("Lumen Foods", "Junior CRM Specialist", "ats:personio", "high", "DE", 52, [("interview", 9, "HR screen"), ("interview", 16, "Round 2"), ("offer", 24, "")]),
    ("Halden Analytics", "Marketing Data Analyst", "ats:ashby", "high", "DE", 47, [("interview", 6, "Case study"), ("offer", 20, ""), ("offer_declined", 26, "")]),
    ("Orbit Travel", "Growth Analyst", "arbeitnow", "high", "DE", 44, [("interview", 11, "Round 1"), ("rejected", 19, "")]),
    ("Marlow & Finch", "Commercial Analyst", "bundesagentur", "medium", "DE", 41, [("rejected", 12, "")]),
    ("Pinecrest Media", "Campaign Coordinator", "linkedin-search", "medium", "DE", 38, [("no_response", 31, "")]),
    ("Brightwave Retail", "Category Analyst", "linkedin-search", "medium", "DE", 36, [("rejected", 8, "")]),
    ("Kestrel Health", "Junior Brand Manager", "ats:greenhouse", "high", "NL", 33, [("interview", 10, "HR screen"), ("interview", 17, "Round 2")]),
    ("Sablewood", "Content Marketing Associate", "arbeitnow", "medium", "DE", 30, [("rejected", 15, "")]),
    ("Alder Bank", "CRM Analyst", "workable", "high", "AT", 29, [("interview", 8, "Phone screen"), ("rejected", 14, "")]),
    ("Tidewater Energy", "Business Development Trainee", "bundesagentur", "medium", "DE", 27, [("withdrawn", 6, "")]),
    ("Quayside Logistics", "Pricing Analyst (Junior)", "ats:personio", "high", "DE", 25, [("interview", 7, "HR screen"), ("interview", 14, "Case study")]),
    ("Juniper Payments", "Lifecycle Marketing Associate", "workable", "high", "NL", 22, []),
    ("Oakline Retail", "Marketplace Analyst", "arbeitnow", "medium", "DE", 20, [("rejected", 9, "")]),
    ("Riverstone Foods", "Sales Operations Analyst", "linkedin-search", "medium", "DE", 18, []),
    ("Glimmer Cosmetics", "CRM Marketing Specialist", "ats:personio", "high", "DE", 16, [("interview", 6, "HR screen")]),
    ("Fernhill Pharma", "Marketing Excellence Trainee", "bundesagentur", "high", "DE", 15, []),
    ("Vela Mobility", "Retention Analyst", "ats:ashby", "high", "DE", 10, [("interview", 5, "Round 1")]),
    ("Copperleaf Commerce", "Growth Marketing Analyst", "ats:greenhouse", "high", "DE", 9, []),
    ("Nordlicht Beauty", "Junior Trade Marketing Manager", "linkedin-search", "medium", "DE", 6, []),
    ("Harbor Analytics", "Customer Insights Analyst", "englishjobs", "medium", "DE", 5, []),
    ("Lumen Foods", "E-commerce Analyst", "ats:personio", "high", "DE", 3, []),
    ("Riverstone Foods", "Commercial Analyst - DACH", "linkedin-search", "high", "DE", 2, []),
    ("Copperleaf Commerce", "Marketing Analyst", "ats:greenhouse", "high", "DE", 1, []),
]
DRAFTS = [("Nordlicht Beauty", "Junior Brand Manager", 4), ("Juniper Payments", "Product Marketing Associate", 6),
          ("Quayside Logistics", "Pricing Analyst", 9)]
DETAILS = {
    "Lumen Foods|Junior CRM Specialist": {"salary": "EUR 50-54k", "contact": "Talent partner: M. Weber", "cv_version": "CV_CRM_v3",
                                          "notes": "Offer call on Thursday; asked for a week to decide"},
    "Halden Analytics|Marketing Data Analyst": {"reason": "accepted a role closer to brand marketing", "salary": "EUR 48k"},
    "Orbit Travel|Growth Analyst": {"reason": "went with a candidate with more paid media experience"},
    "Kestrel Health|Junior Brand Manager": {"contact": "Hiring manager: S. de Vries", "cv_version": "CV_Brand_v2"},
    "Quayside Logistics|Pricing Analyst (Junior)": {"notes": "Case: price change for two customer segments, 30 min presentation"},
    "Glimmer Cosmetics|CRM Marketing Specialist": {"contact": "Recruiter: L. Braun"},
}
NEXT_DATE = {"Kestrel Health|Junior Brand Manager": 2, "Quayside Logistics|Pricing Analyst (Junior)": -2,
             "Glimmer Cosmetics|CRM Marketing Specialist": 5, "Vela Mobility|Retention Analyst": 1,
             "Nordlicht Beauty|Junior Brand Manager": 3}


def slug(*parts):
    return "-".join("".join(c if c.isalnum() else "-" for c in p.lower()).strip("-") for p in parts)


def build_data(folder=DEMO_DIR, today=None):
    """Write a fresh demo dataset into `folder` (removed and recreated)."""
    today = today or datetime.date.today()
    day = lambda n: (today - datetime.timedelta(days=n)).isoformat()
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    os.environ["JOB_RADAR_DATA"] = folder
    seen = {}
    for title, company, loc, country, portal, fit, reason, posted, fresh in JOBS:
        key = URL + slug(company, title)
        v = {"title": title, "company": company, "location": loc, "country": country, "url": key, "portal": portal,
             "status": "ranked", "rank_fit": fit, "rank_reason": reason, "posted_date": day(posted),
             "first_seen": day(0 if fresh else posted), "rank_date": day(0 if fresh else posted),
             "posting_language": "en"}
        if fit == "excluded":
            gate, value, note_field, note = EXCLUDE_NOTES[title]
            v.update({gate: value, note_field: note})
        seen[key] = v
    rows = []
    for company, role, portal, fit, country, ago, path in APPS:
        key = URL + slug(company, role)
        seen.setdefault(key, {"title": role, "company": company, "location": "", "country": country, "url": key,
                              "portal": portal, "status": "ranked", "rank_fit": fit, "rank_reason": "",
                              "first_seen": day(ago + 3), "rank_date": day(ago + 3), "apply_status": "applied"})
        seen[key]["apply_status"] = "applied"
        applications.create(rows, company, role, status="drafted", source=key, job_key=key, when=day(ago + 1))
        ident = applications.app_id(company, role)
        applications.set_status(rows, ident, "applied", when=day(ago))
        for status, after, stage in path:
            applications.set_status(rows, ident, status, stage=stage or None, when=day(ago - after))
        extra = DETAILS.get(f"{company}|{role}", {})
        nd = NEXT_DATE.get(f"{company}|{role}")
        if nd is not None:
            extra = {**extra, "next_date": (today + datetime.timedelta(days=nd)).isoformat()}
        if extra:
            row = applications.find(rows, ident)
            row.update(extra)
    for company, role, deadline_ago in DRAFTS:
        key = URL + slug(company, role)
        applications.create(rows, company, role, status="drafted", source=key, job_key=key if key in seen else "",
                            when=day(deadline_ago))
        nd = NEXT_DATE.get(f"{company}|{role}")
        if nd is not None:
            applications.find(rows, applications.app_id(company, role))["next_date"] = (today + datetime.timedelta(days=nd)).isoformat()
    save_seen({"seen": seen})
    applications.save(rows)
    from .feedback import build_prefs
    build_prefs(seen, rows)
    return folder


def use_demo_profile():
    os.environ["JOB_RADAR_PROFILE"] = config.EXAMPLE_PROFILE
    os.environ["JOB_RADAR_DEMO"] = "1"  # the page shows a "demo data" label
    config.reset()


def cli(args):
    use_demo_profile()
    build_data()
    from . import dashboard
    if args.static:
        data = dashboard.payload()
        os.makedirs(os.path.dirname(os.path.abspath(args.static)), exist_ok=True)
        with open(args.static, "w", encoding="utf-8") as f:
            f.write(dashboard.render(data))
        print(f"demo page: {args.static} (open it in a browser; marks stay in that browser)")
        return
    from . import server
    print("Demo data: fictional companies, rebuilt on every start; your own profile and data are not touched.")
    server.serve(args)
