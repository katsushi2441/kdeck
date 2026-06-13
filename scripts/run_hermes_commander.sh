#!/usr/bin/env bash
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

INTERVAL="${KDECK_HERMES_COMMANDER_INTERVAL_SECONDS:-300}"

while true; do
  scripts/hermes_growth_commander_once.sh || true
  sleep "$INTERVAL"
done
