#!/usr/bin/env bash
# Daily run for cron / launchd: collection (no LLM), then ranking through Claude Code in
# headless mode. Example crontab line (10:00 every day):
#   0 10 * * * /path/to/job-radar/scripts/run_daily.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/runs
log=data/runs/scheduler_stdout.txt
echo "==== $(date -Iseconds) start" >> "$log"
python3 -X utf8 radar.py collect --ensure-today >> "$log" 2>&1
# Stage B needs Claude Code (https://claude.com/claude-code) on the PATH and logged in.
# The allowed tools let it run unattended; it only runs this repo's radar.py and its agents.
claude -p "/daily-rank" \
  --allowedTools "Bash(python3 -X utf8 radar.py:*),Bash(python -X utf8 radar.py:*),Read,Write,Agent,WebSearch,WebFetch" \
  >> "$log" 2>&1
echo "==== $(date -Iseconds) done" >> "$log"
