# Changelog

All notable changes to Job Radar. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-18

### Added
- **Application pipeline.** Applications move through `drafted`, `applied`, `interview`, `offer`, `hired`, or close as `rejected`, `no_response`, `offer_declined`, `withdrawn` (the same vocabulary as ai-job-search's tracker). Each one keeps a stage ("HR screen", "Round 2"), next date, contact, salary, CV version, close reason and notes, and every status change is recorded on its timeline (`data/application_events.jsonl`).
- **Applications board** on the dashboard: one column per stage, drag a card to move it, click it for details and the timeline, add applications found elsewhere.
- **Reminders** for follow-ups, applications that went quiet, upcoming interviews and deadlines, configurable under `[tracking]` in the profile.
- **Insights tab**: applied -> interview -> offer -> hired, overall and by source, fit, country and direction, with the median days to a first reply. An application rejected after an interview still counts as an interview.
- **`python radar.py serve`**: the dashboard on 127.0.0.1 with direct saving, so nothing needs copying or syncing. Writes need a per-start random token and a localhost Host header, the port is bound exclusively, and writes wait while a collection runs.
- `sync-app:` lines, so the static dashboard can move applications too.

### Changed
- The ranking's calibration examples now put roles that led to an interview first, as the strongest signal, ahead of roles you applied to.
- The Jobs table sorts by fit, title, country or posting date with a click on the column header.
- `data/applications.csv` has more columns; older files are read as before and upgraded on the next save.

## [0.2.0] - 2026-10-18

### Added
- **Pluggable sources.** Any job board can be added as one Python file in `sources_custom/` (`NAME`, `FULL_TEXT`, `collect(ctx)`), with a template (`_template.py`) and a complete example (`remotive.py`, Remotive's worldwide remote-jobs API). Custom sources run in order by their full-text flag, and a broken one is skipped without stopping the others.
- **`/add-source <board>`** for Claude Code: checks the site's robots.txt and terms, picks the cleanest public route, writes the source with an offline test, does one live dry run and turns it on in your profile.
- **`company_boards`** in the profile: follow any company's career board (Greenhouse, Lever, Ashby, Personio, Recruitee, SmartRecruiters) in any country from day one.
- `python radar.py sources` lists every built-in and custom source and whether it runs. Unknown source names in the profile are reported instead of silently ignored.

### Changed
- README describes the sources as built-in plus plug-ins, with a new "Adding sources (any country)" section.

## [0.1.0] - 2026-10-18

First public release.

### Added
- Daily collection (no LLM) from the Bundesagentur für Arbeit, Arbeitnow, Workable, englishjobs, optional LinkedIn, and company career feeds on six applicant tracking systems, with a self-growing registry of company boards.
- Deduplication across sources and days, and title rules driven by your direction keywords.
- Full-text pre-screen: years of experience, seniority, language requirements by your CEFR levels, German-written postings, internships that require enrollment, work-permit and visa wording, location.
- Ranking with up to 18 parallel Claude Haiku agents (`/daily-rank`), with structured gates and fit levels, and web verification of snippet-only listings.
- Profile system (`profile/profile.toml`) and `/setup`, which builds the profile from your CV (.pdf, .docx, .md, .txt).
- Self-contained HTML dashboard with filters, status marks and deletion with reasons, synced back through `radar.py sync`; the choices become calibration examples for the next ranking.
- Optional daily email digest over SMTP, credentials from environment variables only.
- Schedulers for Windows (Task Scheduler) and macOS / Linux (cron), and an offline test suite.

[Unreleased]: https://github.com/Yangzhou8833/job-radar/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Yangzhou8833/job-radar/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Yangzhou8833/job-radar/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Yangzhou8833/job-radar/releases/tag/v0.1.0
