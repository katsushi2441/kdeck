#!/usr/bin/env bash
set -euo pipefail

cd /home/kojima/work/kdeck

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

mkdir -p storage

PROMPT_FILE="docs/hermes-growth-commander.md"
CONTEXT="$(python3 scripts/hermes_growth_context.py)"
PROMPT="$(cat "$PROMPT_FILE")

Current context JSON:
${CONTEXT}

Take exactly one commander turn now."

echo "===== $(date --iso-8601=seconds) hermes goal commander =====" | tee -a storage/hermes_growth_commander.log

SESSION_TITLE="kdeck-goal-commander"
HERMES_COMMANDER_PROVIDER="${KDECK_HERMES_COMMANDER_PROVIDER:-}"
HERMES_COMMANDER_MODEL="${KDECK_HERMES_COMMANDER_MODEL:-}"
HERMES_COMMANDER_TIMEOUT="${KDECK_HERMES_COMMANDER_TIMEOUT_SECONDS:-180}"
SESSION_ID="$(hermes sessions list | awk -v title="$SESSION_TITLE" 'NR > 2 && substr($0, 1, length(title)) == title && substr($0, length(title) + 1, 1) == " " {print $NF; exit}')"
SESSION_ARGS=()
if [[ -n "$SESSION_ID" ]]; then
  SESSION_ARGS=(--resume "$SESSION_ID")
fi
MODEL_ARGS=()
if [[ -n "$HERMES_COMMANDER_PROVIDER" ]]; then
  MODEL_ARGS+=(--provider "$HERMES_COMMANDER_PROVIDER")
fi
if [[ -n "$HERMES_COMMANDER_MODEL" ]]; then
  MODEL_ARGS+=(--model "$HERMES_COMMANDER_MODEL")
fi

set +e
OUTPUT=$(
  timeout "$HERMES_COMMANDER_TIMEOUT" hermes chat \
    "${SESSION_ARGS[@]}" \
    "${MODEL_ARGS[@]}" \
    --source kdeck-goal-commander \
    --accept-hooks \
    --pass-session-id \
    --max-turns 60 \
    --quiet \
    -q "$PROMPT" 2>&1
)
STATUS=$?
set -e

printf '%s\n' "$OUTPUT" | tee -a storage/hermes_growth_commander.log
if [[ -z "$SESSION_ID" ]]; then
  NEW_SESSION_ID="$(hermes sessions list | awk 'NR==3 {print $NF; exit}')"
  if [[ -n "$NEW_SESSION_ID" ]]; then
    hermes sessions rename "$NEW_SESSION_ID" "$SESSION_TITLE" >> storage/hermes_growth_commander.log 2>&1 || true
  fi
fi
exit "$STATUS"
