"""Daily email with the jobs worth your attention from one day's ranking.

  - every new high-fit job, English postings first
  - medium-fit jobs with an advantage signal from your profile ([advantage])
  - at most digest.max_local_language German-written postings, in their own section

On a day with nothing to report it still sends a one-line email with the run counts, so
a missing email means the run itself failed.

    python radar.py digest                       # today's ranking, send it
    python radar.py digest --date 2026-10-12 --dry-run   # write the HTML only

Credentials come only from environment variables you set yourself, never from the repo:
JOB_RADAR_SMTP_USER and JOB_RADAR_SMTP_PASSWORD (for Gmail: an app password, which needs
2-Step Verification). The recipient is digest.to in your profile, or the SMTP user.
A copy of every digest is written to reports/daily/<date>.html.
"""
import datetime
import glob
import html
import json
import os
import re
import smtplib
import sys
from email.message import EmailMessage

from . import config
from .collect import load_seen
from .dashboard import SOURCE_LABELS
from .prescreen import read_cached_text


def env(name):
    value = os.environ.get(name)
    if value or sys.platform != "win32":
        return value
    import winreg  # values set with `setx` are not visible to an already running process
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def select(seen, day, profile):
    english, german = [], []
    for v in seen.values():
        if v.get("status") != "ranked" or v.get("rank_date") != day:
            continue
        fit = v.get("rank_fit")
        adv = fit in ("high", "medium") and profile.has_advantage(read_cached_text(v) or "", v.get("company"))
        if not (fit == "high" or (fit == "medium" and adv)):
            continue
        row = dict(v, advantage=adv)
        is_german = v.get("language_flag") == "DE_JD" or v.get("posting_language") == "de"
        (german if is_german else english).append(row)
    order = lambda r: (0 if r.get("rank_fit") == "high" else 1, -int((r.get("posted_date") or "0").replace("-", "") or 0))
    english.sort(key=order)
    german.sort(key=order)
    limit = int(profile.digest.get("max_local_language", 3))
    return english, german[:limit], len(german)


def run_summary(day):
    logs = [p for p in sorted(glob.glob(config.data(config.RUNS, f"{day}_*.json"))) if not p.endswith("_dry.json")]
    if not logs:
        return None
    with open(logs[-1], encoding="utf-8") as f:
        r = json.load(f)
    parts = [f"{SOURCE_LABELS.get(n, n)} {s['added']}" if "added" in s else f"{SOURCE_LABELS.get(n, n)} failed"
             for n, s in r.get("sources", {}).items()]
    return "New postings stored: " + ", ".join(parts)


def job_html(r, profile):
    flags = []
    if r.get("rank_fit") == "medium":
        flags.append("medium fit")
    if r.get("advantage"):
        flags.append(profile.advantage_label)
    if r.get("language_note") and r.get("language_flag") == "DE_JD":
        flags.append(r["language_note"])
    if r.get("experience_gate") == "FAIL_AMBIGUOUS":
        flags.append("experience: " + (r.get("experience_note") or "check"))
    meta = " · ".join(x for x in [r.get("location"), r.get("posted_date") and f"posted {r['posted_date']}",
                                   SOURCE_LABELS.get(r.get("portal"), r.get("portal"))] if x)
    reason = html.escape(r.get("rank_reason") or "")
    return (f'<tr><td style="padding:10px 0;border-bottom:1px solid #e5e7eb">'
            f'<a href="{html.escape(r.get("url") or "")}" style="font-weight:600;color:#1d4ed8;text-decoration:none">'
            f'{html.escape(r.get("title") or "")}</a><br>'
            f'<span style="color:#111827">{html.escape(r.get("company") or "")}</span>'
            f'<span style="color:#6b7280"> · {html.escape(meta)}</span><br>'
            + (f'<span style="color:#374151">{reason}</span><br>' if reason else "")
            + (f'<span style="color:#b45309">{html.escape(" | ".join(flags))}</span>' if flags else "")
            + "</td></tr>")


def build(day, english, german, german_total, summary, profile):
    n = len(english) + len(german)
    subject = f"Job Radar {day}: {n} new job{'s' if n != 1 else ''} worth a look" if n else f"Job Radar {day}: nothing new today"
    body = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;max-width:680px">',
            f'<h2 style="margin:0 0 4px">Job Radar · {day}</h2>']
    if summary:
        body.append(f'<p style="color:#6b7280;margin:0 0 16px">{html.escape(summary)}</p>')
    if english:
        body.append(f'<h3 style="margin:16px 0 0">English postings ({len(english)})</h3><table width="100%" cellspacing="0">')
        body += [job_html(r, profile) for r in english] + ["</table>"]
    if german:
        extra = f", {german_total - len(german)} more on the dashboard" if german_total > len(german) else ""
        body.append(f'<h3 style="margin:20px 0 0">German postings ({len(german)}{extra})</h3><table width="100%" cellspacing="0">')
        body += [job_html(r, profile) for r in german] + ["</table>"]
    if not n:
        body.append("<p>Today's search finished; no new high-fit jobs.</p>")
    body.append('<p style="color:#6b7280;margin-top:20px">Full list: reports/dashboard.html (tick "New in latest run").</p></div>')
    return subject, "\n".join(body)


def plain_text(subject, html_body):
    text = re.sub(r"<br>|</tr>|</h\d>|</p>", "\n", html_body)
    text = re.sub(r"<[^>]+>", "", text)
    return subject + "\n\n" + html.unescape(re.sub(r"\n{3,}", "\n\n", text)).strip()


def cli(args):
    profile = config.get()
    day = args.date or datetime.date.today().isoformat()
    english, german, german_total = select(load_seen()["seen"], day, profile)
    subject, body = build(day, english, german, german_total, run_summary(day), profile)
    os.makedirs(config.DAILY, exist_ok=True)
    out = os.path.join(config.DAILY, f"{day}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset='utf-8'><title>{html.escape(subject)}</title>{body}")
    print(f"{subject} | english={len(english)} german={len(german)}/{german_total} | copy: {config.rel(out)}")
    if args.dry_run:
        return 0
    if not profile.digest.get("enabled"):
        print("not sent: digest.enabled is false in your profile")
        return 0
    marker = config.data(config.RUNS, f"digest_{day}.sent")
    if os.path.exists(marker) and not args.force:
        print("already sent for this date (use --force to resend)")
        return 0
    user, password = env("JOB_RADAR_SMTP_USER"), env("JOB_RADAR_SMTP_PASSWORD")
    if not user or not password:
        print("not sent: set JOB_RADAR_SMTP_USER and JOB_RADAR_SMTP_PASSWORD first (see README)")
        return 2
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, profile.digest.get("to") or user
    msg.set_content(plain_text(subject, body))
    msg.add_alternative(body, subtype="html")
    host, port = profile.digest.get("smtp_host", "smtp.gmail.com"), int(profile.digest.get("smtp_port", 465))
    try:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, password.replace(" ", ""))
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        print("not sent: the mail server rejected the login (for Gmail: 2-Step Verification on, app password current?)")
        return 3
    os.makedirs(config.data(config.RUNS), exist_ok=True)
    with open(marker, "w") as f:
        f.write(datetime.datetime.now().isoformat(timespec="seconds"))
    print(f"sent to {msg['To']}")
    return 0
