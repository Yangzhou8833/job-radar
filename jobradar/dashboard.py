"""Builds reports/dashboard.html: one self-contained page with every ranked job.

    python radar.py dashboard

Open the file in a browser. Filter by fit, country, source or "new in the latest run",
mark a job "ready to apply" or "applied", or delete it with a reason. The page is static
and cannot write to disk, so your marks live in the browser until you press
"Copy sync lines" and paste the result to Claude Code (or into `python radar.py sync`):
applied jobs go into data/applications.csv, and your picks and rejections become
calibration examples for tomorrow's ranking.
"""
import datetime
import html
import json
import os

from . import config, countries
from .collect import load_seen

SOURCE_LABELS = {"linkedin-search": "LinkedIn", "bundesagentur": "Bundesagentur", "arbeitnow": "Arbeitnow",
                 "workable": "Workable", "englishjobs": "englishjobs", "ats:greenhouse": "Greenhouse",
                 "ats:lever": "Lever", "ats:ashby": "Ashby", "ats:personio": "Personio", "ats:recruitee": "Recruitee",
                 "ats:smartrecruiters": "SmartRecruiters"}
GATES = [("work authorization", "work_auth_gate", ("FAIL",)), ("internship", "internship_gate", ("FAIL",)),
         ("experience", "experience_gate", ("FAIL_CLEAR", "FAIL_AMBIGUOUS")), ("language", "language_gate", ("FAIL",))]
FIT_ORDER = {"high": 0, "medium": 1, "low": 2, "excluded": 3, None: 4}


def rows_from(seen):
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
                     "posted": v.get("posted_date"), "firstSeen": v.get("first_seen"),
                     "reason": v.get("rank_reason") or "", "flags": fails,
                     "german": v.get("language_flag") == "DE_JD" or v.get("posting_language") == "de",
                     "status": v.get("apply_status") or "not_applied"})
    rows.sort(key=lambda r: (FIT_ORDER.get(r["fit"], 5), r["german"], -int((r["posted"] or "0").replace("-", "") or 0)))
    return rows


def build(path=None):
    seen = load_seen()["seen"]
    rows = rows_from(seen)
    profile = config.get()
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    title = f"Job Radar - {profile.name}" if profile.name else "Job Radar"
    page = TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload).replace(
        "__UPDATED__", datetime.date.today().isoformat())
    path = path or config.DASHBOARD
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    counts = {k: sum(r["fit"] == k for r in rows) for k in ("high", "medium", "low", "excluded")}
    print(f"dashboard: {config.rel(path)} ({len(rows)} jobs, {counts})")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--text:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;--accent:#2457c5;
--high:#1f7a4d;--high-bg:#e3f3ea;--med:#9a6400;--med-bg:#fbf0d9;--low:#5d5d58;--low-bg:#ececea;--ex:#a33a3a;--ex-bg:#f8e4e4}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1e;--text:#ecebe6;--muted:#a3a29b;--line:#34332f;
--accent:#7ea4ff;--high:#6fd3a0;--high-bg:#183a29;--med:#f0c060;--med-bg:#3b2f14;--low:#c3c2bb;--low-bg:#2c2c2a;--ex:#f08c8c;--ex-bg:#3d1f1f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:20px 16px 8px;max-width:1280px;margin:auto}h1{margin:0;font-size:22px}
.sub{color:var(--muted);margin-top:2px}.wrap{max-width:1280px;margin:auto;padding:0 16px 40px}
.stats{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.stat{background:var(--panel);border:1px solid var(--line);
border-radius:8px;padding:8px 14px;min-width:96px}.stat b{display:block;font-size:20px}.stat span{color:var(--muted);font-size:12px}
.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
select,input,button{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
button{cursor:pointer}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
input[type=search]{min-width:200px;flex:1}label.chk{display:flex;gap:4px;align-items:center;color:var(--muted)}
.table{background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:860px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel)}
td a{color:var(--accent);text-decoration:none;font-weight:600}td a:hover{text-decoration:underline}
.fit{display:inline-block;border-radius:999px;padding:1px 8px;font-size:12px;font-weight:600}
.fit.high{color:var(--high);background:var(--high-bg)}.fit.medium{color:var(--med);background:var(--med-bg)}
.fit.low{color:var(--low);background:var(--low-bg)}.fit.excluded{color:var(--ex);background:var(--ex-bg)}
.muted{color:var(--muted);font-size:12px}.flag{color:var(--med);font-size:12px}.new{color:var(--high);font-size:11px;font-weight:700}
tr.changed{outline:2px solid var(--accent);outline-offset:-2px}.del{border:none;background:none;color:var(--muted);padding:2px 6px}
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--bg);padding:8px 14px;border-radius:6px;display:none}
@media (max-width:640px){header{padding-top:14px}.stat{min-width:72px;padding:6px 10px}}
</style>
</head>
<body>
<header><h1>__TITLE__</h1><div class="sub">Updated __UPDATED__ · marks are kept in this browser until you copy and sync them</div></header>
<div class="wrap">
<div class="stats" id="stats"></div>
<div class="controls">
<select id="fit"><option value="hm">High + medium</option><option value="high">High</option><option value="medium">Medium</option>
<option value="low">Low</option><option value="excluded">Excluded</option><option value="all">All</option></select>
<select id="country"><option value="">All countries</option></select>
<select id="source"><option value="">All sources</option></select>
<select id="status"><option value="">Any status</option><option value="not_applied">Not applied</option>
<option value="ready_to_apply_manually">Ready to apply</option><option value="applied">Applied</option></select>
<label class="chk"><input type="checkbox" id="latest"> New in latest run</label>
<input type="search" id="q" placeholder="Search title, company, reason">
<button class="primary" id="copy">Copy sync lines (<span id="nchg">0</span>)</button>
</div>
<div class="table"><table><thead><tr><th>Fit</th><th>Job</th><th>Where</th><th>Why</th><th>Status</th><th></th></tr></thead>
<tbody id="rows"></tbody></table></div>
<p class="muted" id="foot"></p>
</div>
<div class="toast" id="toast"></div>
<script>
const DATA = __DATA__;
const STORE = "job-radar-marks";
let marks = {status:{}, del:{}};
try { marks = Object.assign(marks, JSON.parse(localStorage.getItem(STORE) || "{}")); } catch (e) {}
const save = () => { try { localStorage.setItem(STORE, JSON.stringify(marks)); } catch (e) {} };
const latest = DATA.reduce((m, r) => (r.firstSeen || "") > m ? r.firstSeen : m, "");
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const statusOf = r => marks.status[r.key] || r.status;
function fill(id, values){ [...new Set(values.filter(Boolean))].sort().forEach(v => { const o = document.createElement("option"); o.value = o.textContent = v; $(id).appendChild(o); }); }
fill("country", DATA.map(r => r.country)); fill("source", DATA.map(r => r.source));
function changes(){
  const out = [];
  for (const r of DATA) {
    if (marks.del[r.key] !== undefined) out.push(`sync-delete: ${r.key}=${marks.del[r.key]}`);
    else if (marks.status[r.key] && marks.status[r.key] !== r.status) out.push(`sync-status: ${r.key}=${marks.status[r.key]}`);
  }
  return out;
}
function render(){
  const f = $("fit").value, c = $("country").value, s = $("source").value, st = $("status").value, q = $("q").value.toLowerCase(), lt = $("latest").checked;
  const live = DATA.filter(r => marks.del[r.key] === undefined);
  const shown = live.filter(r => (f === "all" || (f === "hm" ? (r.fit === "high" || r.fit === "medium") : r.fit === f))
    && (!c || r.country === c) && (!s || r.source === s) && (!st || statusOf(r) === st) && (!lt || r.firstSeen === latest)
    && (!q || `${r.title} ${r.company} ${r.reason}`.toLowerCase().includes(q)));
  const n = k => live.filter(r => r.fit === k).length;
  $("stats").innerHTML = [["High", n("high")], ["Medium", n("medium")], ["Low", n("low")], ["Excluded", n("excluded")],
    ["New in latest run", live.filter(r => r.firstSeen === latest && (r.fit === "high" || r.fit === "medium")).length],
    ["Applied", live.filter(r => statusOf(r) === "applied").length]].map(([l, v]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
  $("rows").innerHTML = shown.slice(0, 1500).map(r => {
    const changed = marks.status[r.key] && marks.status[r.key] !== r.status;
    return `<tr data-key="${esc(r.key)}" class="${changed ? "changed" : ""}">
<td><span class="fit ${esc(r.fit)}">${esc(r.fit)}</span></td>
<td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a> ${r.firstSeen === latest ? '<span class="new">NEW</span>' : ""}<br>${esc(r.company)}<div class="muted">${esc(r.source)}${r.posted ? " · posted " + esc(r.posted) : ""}${r.german ? " · German posting" : ""}</div></td>
<td>${esc(r.location)}<div class="muted">${esc(r.country)}</div></td>
<td>${esc(r.reason)}${r.flags.map(x => `<div class="flag">${esc(x)}</div>`).join("")}</td>
<td><select data-act="status">${[["not_applied","Not applied"],["ready_to_apply_manually","Ready to apply"],["applied","Applied"]].map(([v, l]) => `<option value="${v}" ${statusOf(r) === v ? "selected" : ""}>${l}</option>`).join("")}</select></td>
<td><button class="del" data-act="del" title="Not interested">✕</button></td></tr>`;
  }).join("");
  $("foot").textContent = `${shown.length} of ${live.length} jobs shown` + (shown.length > 1500 ? " (first 1500)" : "");
  $("nchg").textContent = changes().length;
}
$("rows").addEventListener("change", e => {
  if (e.target.dataset.act !== "status") return;
  const key = e.target.closest("tr").dataset.key; marks.status[key] = e.target.value; save(); render();
});
$("rows").addEventListener("click", e => {
  if (e.target.dataset.act !== "del") return;
  const key = e.target.closest("tr").dataset.key;
  const reason = prompt("Why is this job not for you? (optional, helps the ranking learn)");
  if (reason === null) return;
  marks.del[key] = reason.replace(/[\r\n]+/g, " ").trim(); save(); render();
});
["fit", "country", "source", "status", "latest", "q"].forEach(id => $(id).addEventListener("input", render));
$("copy").addEventListener("click", async () => {
  const lines = changes();
  if (!lines.length) return toast("Nothing to sync yet");
  const text = lines.join("\n");
  try { await navigator.clipboard.writeText(text); toast(`Copied ${lines.length} lines. Paste them to Claude Code.`); }
  catch (e) { window.prompt("Copy these lines:", text); }
});
function toast(msg){ const t = $("toast"); t.textContent = msg; t.style.display = "block"; setTimeout(() => t.style.display = "none", 2600); }
render();
</script>
</body>
</html>
"""
