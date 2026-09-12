#!/usr/bin/env bash
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

load_env() {
  if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
}

load_env

INTERVAL="${KDECK_HERMES_COMMANDER_INTERVAL_SECONDS:-300}"

while true; do
  # .env は毎回読み直す。外で1回だけ読むと、トークンを更新しても
  # このプロセスを再起動するまで古い値を子プロセスへ渡し続ける
  # （2026-09-13 に kdeck の goal runner で実際に発生し、31時間 enqueue が 403 で落ちていた）。
  load_env
  scripts/hermes_growth_commander_once.sh || true
  sleep "$INTERVAL"
done
