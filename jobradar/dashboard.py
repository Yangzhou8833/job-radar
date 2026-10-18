"""The dashboard: jobs, your applications pipeline, and insights, in one page.

    python radar.py serve        # live: every click is saved directly (recommended)
    python radar.py dashboard    # writes reports/dashboard.html, a static file

Three tabs:
  Jobs          every ranked job, filterable; mark "ready to apply" / "applied", or delete
                with a reason
  Applications  a board of your applications by status (drafted, applied, interview, offer,
                closed): drag a card to move it, click it for details (stage, next date,
                contact, salary, CV version, notes) and its timeline; reminders for
                follow-ups, upcoming interviews and deadlines
  Insights      applied -> interview -> offer -> hired, overall and by source, fit,
                country and direction, plus the median days to a first reply

Opened as a static file the page cannot write to disk: marks stay in the browser until you
press "Copy sync lines" and paste the result to Claude Code (or `python radar.py sync`), and
application details can only be edited in serve mode.
"""
import datetime
import html
import json
import os

from . import applications, config, countries
from .collect import load_seen

SOURCE_LABELS = {"linkedin-search": "LinkedIn", "bundesagentur": "Bundesagentur", "arbeitnow": "Arbeitnow",
                 "workable": "Workable", "englishjobs": "englishjobs", "ats:greenhouse": "Greenhouse",
                 "ats:lever": "Lever", "ats:ashby": "Ashby", "ats:personio": "Personio", "ats:recruitee": "Recruitee",
                 "ats:smartrecruiters": "SmartRecruiters", "remotive": "Remotive"}
GATES = [("work authorization", "work_auth_gate", ("FAIL",)), ("internship", "internship_gate", ("FAIL",)),
         ("experience", "experience_gate", ("FAIL_CLEAR", "FAIL_AMBIGUOUS")), ("language", "language_gate", ("FAIL",))]
FIT_ORDER = {"high": 0, "medium": 1, "low": 2, "excluded": 3, None: 4}


def rows_from(seen, app_by_job=None):
    app_by_job = app_by_job or {}
    rows = []
    for key, v in seen.items():
        if v.get("status") != "ranked" or v.get("user_feedback") == "not_interested":
            continue
        fit = v.get("rank_fit")
        fails = [f"{label}: {v.get(field.replace('_gate', '_note')) or 'see posting'}"
                 for label, field, bad in GATES if v.get(field) in bad]
        code = v.get("country")
        rows.append({"key": key, "fit": fit, "title": v.get("title"), "company": v.get("company"),
                     "location": v.get("location"), "country": countries.workable_name(code) if code else "",
                     "url": v.get("url"), "source": SOURCE_LABELS.get(v.get("portal"), v.get("portal") or ""),
                     "posted": v.get("posted_date"), "firstSeen": v.get("first_seen"), "deadline": v.get("deadline"),
                     "reason": v.get("rank_reason") or "", "flags": fails,
                     "german": v.get("language_flag") == "DE_JD" or v.get("posting_language") == "de",
                     "status": v.get("apply_status") or "not_applied", "app": app_by_job.get(key)})
    rows.sort(key=lambda r: (FIT_ORDER.get(r["fit"], 5), r["german"], -int((r["posted"] or "0").replace("-", "") or 0)))
    return rows


def payload(seen=None, profile=None):
    """Everything the page shows, computed in Python so the static and live pages agree."""
    seen = load_seen()["seen"] if seen is None else seen
    profile = profile or config.get()
    apps, events = applications.load(), applications.load_events()
    app_by_job = {r["job_key"]: r["id"] for r in apps if r.get("job_key")}
    app_rows = []
    for r in apps:
        v = seen.get(r.get("job_key")) or {}
        app_rows.append({**{k: r.get(k, "") for k in applications.FIELDS},
                         "url": r.get("source") or v.get("url") or "", "fit": v.get("rank_fit") or "",
                         "lastActivity": applications.last_activity(r, events),
                         "timeline": applications.timeline(events, r["id"])})
    return {"name": profile.name, "updated": datetime.date.today().isoformat(),
            "jobs": rows_from(seen, app_by_job), "apps": app_rows,
            "reminders": applications.reminders(apps, events, profile),
            "funnel": applications.funnel(apps, events, seen, profile),
            "statuses": list(applications.STATUSES), "final": list(applications.FINAL)}


def render(data, token=None):
    """The page for `data`; with a token it saves through the local server (serve mode)."""
    title = f"Job Radar - {data['name']}" if data.get("name") else "Job Radar"
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", blob)
            .replace("__LIVE__", json.dumps(token)))


def build(path=None):
    data = payload()
    path = path or config.DASHBOARD
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(data))
    counts = {k: sum(r["fit"] == k for r in data["jobs"]) for k in ("high", "medium", "low", "excluded")}
    print(f"dashboard: {config.rel(path)} ({len(data['jobs'])} jobs {counts}, {len(data['apps'])} applications, "
          f"{len(data['reminders'])} reminders)")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--sunk:#f0efeb;--text:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;--accent:#2457c5;--accent-bg:#e6edfb;
--high:#1f7a4d;--high-bg:#e3f3ea;--med:#9a6400;--med-bg:#fbf0d9;--low:#5d5d58;--low-bg:#ececea;--ex:#a33a3a;--ex-bg:#f8e4e4}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1e;--sunk:#191918;--text:#ecebe6;--muted:#a3a29b;--line:#34332f;
--accent:#7ea4ff;--accent-bg:#1f2b45;--high:#6fd3a0;--high-bg:#183a29;--med:#f0c060;--med-bg:#3b2f14;--low:#c3c2bb;--low-bg:#2c2c2a;--ex:#f08c8c;--ex-bg:#3d1f1f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:18px 16px 0;max-width:1320px;margin:auto}h1{margin:0;font-size:22px}.sub{color:var(--muted);margin-top:2px;font-size:13px}
.wrap{max-width:1320px;margin:auto;padding:0 16px 40px}
nav{display:flex;gap:4px;margin:14px 0 12px;border-bottom:1px solid var(--line)}
nav button{border:none;background:none;padding:8px 12px;border-bottom:2px solid transparent;border-radius:0;color:var(--muted);font-weight:600}
nav button.on{color:var(--text);border-bottom-color:var(--accent)}.count{font-weight:400;color:var(--muted)}
.dot{display:inline-block;min-width:18px;padding:0 5px;border-radius:9px;background:var(--ex);color:#fff;font-size:11px;text-align:center;margin-left:4px}
.stats{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 14px;min-width:100px}
.stat b{display:block;font-size:20px}.stat span{color:var(--muted);font-size:12px}
.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
select,input,textarea,button{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
button{cursor:pointer}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}button:disabled{opacity:.5;cursor:default}
input[type=search]{min-width:180px;flex:1}label.chk{display:flex;gap:4px;align-items:center;color:var(--muted)}
.table{background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow-x:auto}
table{border-collapse:collapse;width:100%}#jobs table{min-width:860px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600;background:var(--panel)}th.sort{cursor:pointer;user-select:none}th.sort:hover{color:var(--text)}
td a{color:var(--accent);text-decoration:none;font-weight:600}td a:hover{text-decoration:underline}
.pill{display:inline-block;border-radius:999px;padding:1px 8px;font-size:12px;font-weight:600;white-space:nowrap}
.high{color:var(--high);background:var(--high-bg)}.medium{color:var(--med);background:var(--med-bg)}.low{color:var(--low);background:var(--low-bg)}.excluded{color:var(--ex);background:var(--ex-bg)}
.s-drafted{color:var(--low);background:var(--low-bg)}.s-applied{color:var(--accent);background:var(--accent-bg)}.s-interview{color:var(--med);background:var(--med-bg)}
.s-offer,.s-hired{color:var(--high);background:var(--high-bg)}.s-rejected,.s-no_response,.s-offer_declined,.s-withdrawn{color:var(--muted);background:var(--sunk)}
.muted{color:var(--muted);font-size:12px}.flag{color:var(--med);font-size:12px}.new{color:var(--high);font-size:11px;font-weight:700}
.del{border:none;background:none;color:var(--muted);padding:2px 6px}
.board{display:grid;grid-template-columns:repeat(5,minmax(220px,1fr));gap:10px;overflow-x:auto;padding-bottom:6px}
.col{background:var(--sunk);border:1px solid var(--line);border-radius:8px;padding:8px;min-height:160px}.col.over{outline:2px dashed var(--accent)}
.col h3{margin:2px 4px 8px;font-size:13px;display:flex;justify-content:space-between;color:var(--muted)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:8px 10px;margin-bottom:8px;cursor:pointer}
.card:hover{border-color:var(--accent)}.card b{display:block}.card .muted{margin-top:2px}.badge{display:inline-block;font-size:11px;margin-top:4px;padding:1px 6px;border-radius:4px;background:var(--med-bg);color:var(--med)}
.badge.hot{background:var(--ex-bg);color:var(--ex)}
.reminders{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--med);border-radius:8px;padding:10px 14px;margin-bottom:14px}
.reminders li{margin:2px 0}.reminders a{color:var(--accent);cursor:pointer}
.funnel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:14px}
.bar{display:flex;align-items:center;gap:10px;margin:6px 0}.bar span.l{width:80px;color:var(--muted)}.bar div.t{flex:1;background:var(--sunk);border-radius:4px;height:22px}
.bar div.f{height:22px;border-radius:4px;background:var(--accent);min-width:2px}.bar span.n{width:90px;text-align:right}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.grid2 h3{margin:0 0 6px;font-size:14px}
table.mini{table-layout:fixed}table.mini th:first-child{width:38%}table.mini th,table.mini td{padding:6px 8px;overflow-wrap:anywhere}table.mini td:not(:first-child),table.mini th:not(:first-child){text-align:right}
dialog{border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--text);width:min(560px,calc(100vw - 32px));padding:0}
dialog::backdrop{background:rgba(0,0,0,.35)}.dlg{padding:16px 18px}.dlg h2{margin:0 0 2px;font-size:17px}
.form{display:grid;grid-template-columns:1fr 1fr;gap:8px 10px;margin:12px 0}.form label{display:flex;flex-direction:column;font-size:12px;color:var(--muted);gap:3px}
.form .wide{grid-column:1/-1}.form textarea{min-height:64px}.acts{display:flex;gap:8px;justify-content:flex-end;margin-top:10px}
.tl{border-left:2px solid var(--line);margin:8px 0 0 4px;padding-left:12px;max-height:160px;overflow-y:auto}.tl div{margin:4px 0;font-size:12px}
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--bg);padding:8px 14px;border-radius:6px;display:none;z-index:9}
.live{color:var(--high)}[hidden]{display:none!important}
@media (max-width:640px){.form{grid-template-columns:1fr}.stat{min-width:76px;padding:6px 10px}}
</style>
</head>
<body>
<header><h1>__TITLE__</h1><div class="sub" id="sub"></div>
<nav><button data-tab="jobs" class="on">Jobs <span class="count" id="n-jobs"></span></button>
<button data-tab="apps">Applications <span class="count" id="n-apps"></span><span id="n-rem"></span></button>
<button data-tab="insights">Insights</button></nav></header>
<div class="wrap">

<section id="jobs">
<div class="stats" id="job-stats"></div>
<div class="controls">
<select id="fit"><option value="hm">High + medium</option><option value="high">High</option><option value="medium">Medium</option>
<option value="low">Low</option><option value="excluded">Excluded</option><option value="all">All</option></select>
<select id="country"><option value="">All countries</option></select>
<select id="source"><option value="">All sources</option></select>
<select id="status"><option value="">Any status</option><option value="not_applied">Not applied</option>
<option value="ready_to_apply_manually">Ready to apply</option><option value="applied">Applied</option></select>
<label class="chk"><input type="checkbox" id="latest"> New in latest run</label>
<input type="search" id="q" placeholder="Search title, company, reason">
<button class="primary syncbtn" hidden>Copy sync lines (<span class="nchg">0</span>)</button>
</div>
<div class="table"><table><thead><tr><th class="sort" data-sort="fit">Fit</th><th class="sort" data-sort="title">Job</th>
<th class="sort" data-sort="country">Where</th><th>Why</th><th class="sort" data-sort="posted">Posted</th><th>Status</th><th></th></tr></thead>
<tbody id="job-rows"></tbody></table></div>
<p class="muted" id="job-foot"></p>
</section>

<section id="apps" hidden>
<div class="reminders" id="reminders" hidden></div>
<div class="controls"><input type="search" id="aq" placeholder="Search company, role, notes">
<button id="add-app" hidden>+ Add application</button>
<button class="primary syncbtn" hidden>Copy sync lines (<span class="nchg">0</span>)</button></div>
<div class="board" id="board"></div>
<p class="muted" id="app-foot"></p>
</section>

<section id="insights" hidden>
<div class="stats" id="kpis"></div>
<div class="funnel"><h3 style="margin:0 0 6px;font-size:14px">Funnel</h3><div id="funnel"></div></div>
<div class="grid2" id="splits"></div>
<p class="muted" id="ins-foot"></p>
</section>
</div>

<dialog id="dlg"><div class="dlg">
<h2 id="d-title"></h2><div class="muted" id="d-sub"></div>
<div class="form">
<label>Status<select id="d-status"></select></label>
<label>Stage (e.g. HR screen, Round 2, Case)<input id="d-stage"></label>
<label>Next date (interview or deadline)<input id="d-next_date" type="date"></label>
<label>Applied on<input id="d-date" type="date"></label>
<label>Contact<input id="d-contact"></label>
<label>Salary<input id="d-salary"></label>
<label>CV / cover letter version<input id="d-cv_version"></label>
<label>Reason (if closed)<input id="d-reason"></label>
<label class="wide">Posting link<input id="d-source"></label>
<label class="wide">Notes<textarea id="d-notes"></textarea></label>
</div>
<div class="muted" id="d-static" hidden>Opened as a file: only the status can be changed here (copy sync lines afterwards). Run <b>python radar.py serve</b> to edit every field.</div>
<div class="muted" style="margin-top:8px">Timeline</div><div class="tl" id="d-tl"></div>
<div class="acts"><button id="d-cancel">Close</button><button class="primary" id="d-save">Save</button></div>
</div></dialog>

<dialog id="new"><div class="dlg"><h2>Add application</h2>
<div class="form"><label>Company<input id="n-company"></label><label>Role<input id="n-role"></label>
<label>Status<select id="n-status"></select></label><label>Posting link<input id="n-source"></label>
<label class="wide">Notes<textarea id="n-notes"></textarea></label></div>
<div class="acts"><button id="n-cancel">Cancel</button><button class="primary" id="n-save">Add</button></div></div></dialog>
<div class="toast" id="toast"></div>

<script>
let DATA = __DATA__;
const LIVE = __LIVE__;           // token from `radar.py serve`, null when opened as a file
const STORE = "job-radar-marks";
const COLS = [["drafted", "Drafted"], ["applied", "Applied"], ["interview", "Interview"], ["offer", "Offer"], ["closed", "Closed"]];
const LABEL = {drafted:"Drafted", applied:"Applied", interview:"Interview", offer:"Offer", hired:"Hired", rejected:"Rejected",
  no_response:"No response", offer_declined:"Offer declined", withdrawn:"Withdrawn"};
let marks = {status:{}, del:{}, app:{}}, sortKey = null, sortDir = 1, current = null;
if (!LIVE) { try { marks = Object.assign(marks, JSON.parse(localStorage.getItem(STORE) || "{}")); } catch (e) {} }
const save = () => { try { localStorage.setItem(STORE, JSON.stringify(marks)); } catch (e) {} };
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const jobStatus = r => marks.status[r.key] || r.status;
const appStatus = a => marks.app[a.id] || a.status;
const column = s => DATA.final.includes(s) ? "closed" : s;
const latest = () => DATA.jobs.reduce((m, r) => (r.firstSeen || "") > m ? r.firstSeen : m, "");
const daysSince = d => d ? Math.round((Date.now() - new Date(d + "T00:00:00")) / 864e5) : null;

async function api(path, body){
  try {
    const r = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json", "X-Radar-Token":LIVE}, body:JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    DATA = j; renderAll(); return true;
  } catch (e) { toast("Not saved: " + e.message); return false; }
}

// ------------------------------------------------------------ jobs
function fillOptions(){
  for (const [id, key] of [["country", "country"], ["source", "source"]]) {
    const sel = $(id), keep = sel.value;
    sel.querySelectorAll("option:not(:first-child)").forEach(o => o.remove());
    [...new Set(DATA.jobs.map(r => r[key]).filter(Boolean))].sort().forEach(v => { const o = document.createElement("option"); o.value = o.textContent = v; sel.appendChild(o); });
    sel.value = keep;
  }
}
function renderJobs(){
  const f = $("fit").value, c = $("country").value, s = $("source").value, st = $("status").value, q = $("q").value.toLowerCase(), lt = $("latest").checked, last = latest();
  const live = DATA.jobs.filter(r => marks.del[r.key] === undefined);
  let shown = live.filter(r => (f === "all" || (f === "hm" ? (r.fit === "high" || r.fit === "medium") : r.fit === f))
    && (!c || r.country === c) && (!s || r.source === s) && (!st || jobStatus(r) === st) && (!lt || r.firstSeen === last)
    && (!q || `${r.title} ${r.company} ${r.reason}`.toLowerCase().includes(q)));
  if (sortKey) {
    const rank = {high:0, medium:1, low:2, excluded:3};
    shown = shown.slice().sort((a, b) => {
      const x = sortKey === "fit" ? rank[a.fit] ?? 9 : (a[sortKey] || ""), y = sortKey === "fit" ? rank[b.fit] ?? 9 : (b[sortKey] || "");
      return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
    });
  }
  const n = k => live.filter(r => r.fit === k).length;
  $("job-stats").innerHTML = [["High", n("high")], ["Medium", n("medium")], ["Low", n("low")], ["Excluded", n("excluded")],
    ["New in latest run", live.filter(r => r.firstSeen === last && (r.fit === "high" || r.fit === "medium")).length]]
    .map(([l, v]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
  $("job-rows").innerHTML = shown.slice(0, 1500).map(r => `<tr data-key="${esc(r.key)}">
<td><span class="pill ${esc(r.fit)}">${esc(r.fit)}</span></td>
<td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a> ${r.firstSeen === last ? '<span class="new">NEW</span>' : ""}<br>${esc(r.company)}
<div class="muted">${esc(r.source)}${r.german ? " · German posting" : ""}${r.deadline ? " · deadline " + esc(r.deadline) : ""}</div></td>
<td>${esc(r.location)}<div class="muted">${esc(r.country)}</div></td>
<td>${esc(r.reason)}${r.flags.map(x => `<div class="flag">${esc(x)}</div>`).join("")}</td>
<td class="muted">${esc(r.posted || "")}</td>
<td><select data-act="jstatus">${[["not_applied","Not applied"],["ready_to_apply_manually","Ready to apply"],["applied","Applied"]].map(([v, l]) => `<option value="${v}" ${jobStatus(r) === v ? "selected" : ""}>${l}</option>`).join("")}</select>
${r.app ? '<div class="muted"><a data-act="openapp" data-id="' + esc(r.app) + '">open application</a></div>' : ""}</td>
<td><button class="del" data-act="del" title="Not interested">✕</button></td></tr>`).join("");
  $("job-foot").textContent = `${shown.length} of ${live.length} jobs shown` + (shown.length > 1500 ? " (first 1500)" : "");
}

// ------------------------------------------------------------ applications
function reminderBadge(a){
  const r = DATA.reminders.find(x => x.id === a.id);
  return r ? `<span class="badge ${r.kind === "upcoming" || r.kind === "deadline" ? "hot" : ""}">${esc(r.text)}</span>` : "";
}
function renderApps(){
  const q = $("aq").value.toLowerCase();
  const apps = DATA.apps.filter(a => !q || `${a.company} ${a.role} ${a.notes} ${a.stage}`.toLowerCase().includes(q));
  $("board").innerHTML = COLS.map(([key, label]) => {
    const cards = apps.filter(a => column(appStatus(a)) === key).sort((a, b) => (b.lastActivity || "").localeCompare(a.lastActivity || ""));
    return `<div class="col" data-col="${key}"><h3><span>${label}</span><span>${cards.length}</span></h3>${cards.map(a => {
      const since = daysSince(a.lastActivity);
      return `<div class="card" draggable="true" data-id="${esc(a.id)}"><b>${esc(a.company)}</b>${esc(a.role)}
<div class="muted">${key === "closed" ? `<span class="pill s-${esc(appStatus(a))}">${esc(LABEL[appStatus(a)] || appStatus(a))}</span> ` : ""}${a.stage ? esc(a.stage) + " · " : ""}${a.date ? "applied " + esc(a.date) : "not sent yet"}${since !== null ? ` · ${since}d ago` : ""}</div>
${a.next_date && key !== "closed" ? `<div class="muted">next: ${esc(a.next_date)}</div>` : ""}${reminderBadge(a)}</div>`;
    }).join("")}</div>`;
  }).join("");
  const rem = DATA.reminders;
  $("reminders").hidden = !rem.length;
  $("reminders").innerHTML = `<b>${rem.length} need${rem.length === 1 ? "s" : ""} attention</b><ul style="margin:6px 0 0;padding-left:18px">${rem.map(r =>
    `<li><a data-act="openapp" data-id="${esc(r.id)}">${esc(r.company)} · ${esc(r.role)}</a>: ${esc(r.text)}</li>`).join("")}</ul>`;
  $("app-foot").textContent = LIVE ? "Drag a card to change its status; click it for details." :
    "Drag a card to change its status (copy sync lines afterwards). Run python radar.py serve to edit details.";
}
function openApp(id, presetStatus){
  const a = DATA.apps.find(x => x.id === id); if (!a) return;
  current = a;
  $("d-title").textContent = `${a.role} @ ${a.company}`;
  $("d-sub").innerHTML = (a.fit ? `fit <span class="pill ${esc(a.fit)}">${esc(a.fit)}</span> · ` : "") + (a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">posting</a>` : "no link");
  $("d-status").innerHTML = DATA.statuses.map(s => `<option value="${s}">${LABEL[s]}</option>`).join("");
  $("d-status").value = presetStatus || appStatus(a);
  for (const f of ["stage", "next_date", "date", "contact", "salary", "cv_version", "reason", "source", "notes"]) {
    const el = $("d-" + f); el.value = a[f] || ""; el.disabled = !LIVE;
  }
  $("d-static").hidden = !!LIVE;
  $("d-tl").innerHTML = (a.timeline || []).slice().reverse().map(e => `<div><b>${esc(e.at)}</b> ${e.from ? esc(LABEL[e.from] || e.from) + " → " : ""}${esc(LABEL[e.to] || e.to)}${e.stage ? " · " + esc(e.stage) : ""}${e.note ? " · " + esc(e.note) : ""}</div>`).join("") || '<div class="muted">no changes recorded yet</div>';
  $("dlg").showModal();
  if (presetStatus && DATA.final.includes(presetStatus)) $("d-reason").focus();
}
async function saveApp(){
  const a = current; if (!a) return;
  const status = $("d-status").value;
  if (!LIVE) { if (status !== a.status) marks.app[a.id] = status; else delete marks.app[a.id]; save(); $("dlg").close(); renderAll(); return; }
  const fields = {};
  for (const f of ["stage", "next_date", "date", "contact", "salary", "cv_version", "reason", "source", "notes"]) fields[f] = $("d-" + f).value;
  const ok = await api("/api/app", {id:a.id, status, fields});
  if (ok) { $("dlg").close(); toast("Saved"); }
}
async function moveApp(id, col){
  const a = DATA.apps.find(x => x.id === id); if (!a || column(appStatus(a)) === col) return;
  if (col === "closed") return openApp(id, "rejected");
  if (!LIVE) { marks.app[id] = col; save(); renderAll(); return; }
  await api("/api/app", {id, status:col});
}

// ------------------------------------------------------------ insights
function renderInsights(){
  const F = DATA.funnel, o = F.overall, top = Math.max(o.applied, 1);
  $("kpis").innerHTML = [["Open applications", F.open], ["Applied", o.applied], ["Interview rate", o.interview_rate === null ? "-" : o.interview_rate + "%"],
    ["Offers", o.offer], ["Median days to reply", F.median_days_to_reply ?? "-"]].map(([l, v]) => `<div class="stat"><b>${esc(v)}</b><span>${l}</span></div>`).join("");
  $("funnel").innerHTML = [["applied", "Applied"], ["interview", "Interview"], ["offer", "Offer"], ["hired", "Hired"]].map(([k, l], i, all) => {
    const prev = i ? o[all[i - 1][0]] : null, rate = i && prev ? ` (${Math.round(100 * o[k] / prev)}%)` : "";
    return `<div class="bar"><span class="l">${l}</span><div class="t"><div class="f" style="width:${100 * o[k] / top}%"></div></div><span class="n">${o[k]}${rate}</span></div>`;
  }).join("");
  const names = {source:"By source", fit:"By fit", country:"By country", direction:"By direction"};
  $("splits").innerHTML = Object.entries(F.by).map(([dim, rows]) => `<div class="table"><div style="padding:10px 10px 0"><h3>${names[dim]}</h3></div>
<table class="mini"><thead><tr><th></th><th>Applied</th><th>Interview</th><th>Offer</th><th title="Interview rate">Rate</th></tr></thead><tbody>${rows.map(r =>
    `<tr><td>${esc(r.label)}</td><td>${r.applied}</td><td>${r.interview}</td><td>${r.offer}</td><td>${r.interview_rate === null ? "-" : r.interview_rate + "%"}</td></tr>`).join("")
    || '<tr><td colspan="5" class="muted">no applications yet</td></tr>'}</tbody></table></div>`).join("");
  $("ins-foot").textContent = "Counts how far each application got, so a rejection after an interview still counts as an interview." +
    (LIVE ? "" : " Opened as a file: reflects the last saved data, not unsynced marks.");
}

// ------------------------------------------------------------ shared
function changes(){
  const out = [];
  for (const r of DATA.jobs) {
    if (marks.del[r.key] !== undefined) out.push(`sync-delete: ${r.key}=${marks.del[r.key]}`);
    else if (marks.status[r.key] && marks.status[r.key] !== r.status) out.push(`sync-status: ${r.key}=${marks.status[r.key]}`);
  }
  for (const a of DATA.apps) if (marks.app[a.id] && marks.app[a.id] !== a.status) out.push(`sync-app: ${a.id}=${marks.app[a.id]}`);
  return out;
}
function renderAll(){
  fillOptions(); renderJobs(); renderApps(); renderInsights();
  const live = DATA.jobs.filter(r => marks.del[r.key] === undefined);
  $("n-jobs").textContent = `(${live.filter(r => r.fit === "high" || r.fit === "medium").length})`;
  $("n-apps").textContent = `(${DATA.funnel.open})`;
  $("n-rem").innerHTML = DATA.reminders.length ? `<span class="dot">${DATA.reminders.length}</span>` : "";
  document.querySelectorAll(".nchg").forEach(e => e.textContent = changes().length);
  $("sub").innerHTML = `Updated ${esc(DATA.updated)} · ` + (LIVE ? '<span class="live">● live: changes are saved directly</span>' :
    "opened as a file: marks stay in this browser until you copy and sync them");
}
document.querySelectorAll("nav button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.toggle("on", x === b));
  for (const id of ["jobs", "apps", "insights"]) $(id).hidden = id !== b.dataset.tab;
  try { localStorage.setItem("job-radar-tab", b.dataset.tab); } catch (e) {}
}));
document.querySelectorAll("th.sort").forEach(th => th.addEventListener("click", () => {
  sortDir = sortKey === th.dataset.sort ? -sortDir : 1; sortKey = th.dataset.sort; renderJobs();
}));
document.addEventListener("click", e => {
  const t = e.target.closest("[data-act=openapp]"); if (t) { e.preventDefault(); return openApp(t.dataset.id); }
  const card = e.target.closest(".card"); if (card) return openApp(card.dataset.id);
});
$("job-rows").addEventListener("change", async e => {
  if (e.target.dataset.act !== "jstatus") return;
  const key = e.target.closest("tr").dataset.key;
  if (LIVE) { await api("/api/job", {key, status:e.target.value}); if (e.target.value === "applied") toast("Added to Applications"); }
  else { marks.status[key] = e.target.value; save(); renderAll(); }
});
$("job-rows").addEventListener("click", async e => {
  if (e.target.dataset.act !== "del") return;
  const key = e.target.closest("tr").dataset.key;
  const reason = prompt("Why is this job not for you? (optional, helps the ranking learn)");
  if (reason === null) return;
  const clean = reason.replace(/[\r\n]+/g, " ").trim();
  if (LIVE) await api("/api/job/delete", {key, reason:clean}); else { marks.del[key] = clean; save(); renderAll(); }
});
["fit", "country", "source", "status", "latest", "q"].forEach(id => $(id).addEventListener("input", renderJobs));
$("aq").addEventListener("input", renderApps);
$("board").addEventListener("dragstart", e => { const c = e.target.closest(".card"); if (c) e.dataTransfer.setData("text/plain", c.dataset.id); });
$("board").addEventListener("dragover", e => { const c = e.target.closest(".col"); if (c) { e.preventDefault(); c.classList.add("over"); } });
$("board").addEventListener("dragleave", e => { const c = e.target.closest(".col"); if (c) c.classList.remove("over"); });
$("board").addEventListener("drop", e => { const c = e.target.closest(".col"); if (!c) return; e.preventDefault(); c.classList.remove("over"); moveApp(e.dataTransfer.getData("text/plain"), c.dataset.col); });
$("d-save").addEventListener("click", saveApp); $("d-cancel").addEventListener("click", () => $("dlg").close());
$("add-app").hidden = !LIVE;
$("add-app").addEventListener("click", () => {
  $("n-status").innerHTML = DATA.statuses.map(s => `<option value="${s}" ${s === "applied" ? "selected" : ""}>${LABEL[s]}</option>`).join("");
  for (const f of ["company", "role", "source", "notes"]) $("n-" + f).value = "";
  $("new").showModal();
});
$("n-cancel").addEventListener("click", () => $("new").close());
$("n-save").addEventListener("click", async () => {
  const body = {company:$("n-company").value.trim(), role:$("n-role").value.trim(), status:$("n-status").value, source:$("n-source").value.trim(), notes:$("n-notes").value.trim()};
  if (!body.company || !body.role) return toast("Company and role are needed");
  if (await api("/api/app/new", body)) { $("new").close(); toast("Added"); }
});
document.querySelectorAll(".syncbtn").forEach(b => { b.hidden = !!LIVE; b.addEventListener("click", async () => {
  const lines = changes();
  if (!lines.length) return toast("Nothing to sync yet");
  const text = lines.join("\n");
  try { await navigator.clipboard.writeText(text); toast(`Copied ${lines.length} lines. Paste them to Claude Code.`); }
  catch (e) { window.prompt("Copy these lines:", text); }
}); });
function toast(msg){ const t = $("toast"); t.textContent = msg; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", 2600); }
try { const tab = localStorage.getItem("job-radar-tab"); if (tab) document.querySelector(`nav button[data-tab="${tab}"]`)?.click(); } catch (e) {}
renderAll();
</script>
</body>
</html>
"""
