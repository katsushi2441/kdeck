#!/usr/bin/env bash
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

mkdir -p storage

PROMPT="Run shell: python3 -m app.commander_tool brief . Read next_goal only. If next_goal is null or eligible is false, do not enqueue anything. If next_goal.eligible is true, run: python3 -m app.commander_tool enqueue NEXT_GOAL_NAME . Never skip to a lower priority goal. Reply briefly in Japanese."

echo "===== $(date --iso-8601=seconds) kdeck hermes commander turn =====" | tee -a storage/hermes_commander.log

set +e
OUTPUT=$(
  hermes chat \
    -q "$PROMPT" \
    --source kdeck-commander \
    --accept-hooks \
    --yolo \
    --max-turns 20 \
    --quiet 2>&1
)
STATUS=$?
set -e

printf '%s\n' "$OUTPUT" | tee -a storage/hermes_commander.log
exit "$STATUS"
