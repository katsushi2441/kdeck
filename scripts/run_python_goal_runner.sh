#!/usr/bin/env bash
set -euo pipefail

cd /home/kojima/work/kdeck

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

INTERVAL="${KDECK_PYTHON_GOAL_RUNNER_INTERVAL_SECONDS:-120}"
mkdir -p storage

while true; do
  {
    echo "===== $(date --iso-8601=seconds) kdeck python goal runner ====="
    python3 -m app.commander_tool growth-cycle
  } >> storage/python_goal_runner.log 2>&1 || true
  sleep "$INTERVAL"
done
