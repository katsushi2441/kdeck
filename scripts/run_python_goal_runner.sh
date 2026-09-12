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
INTERVAL="${KDECK_PYTHON_GOAL_RUNNER_INTERVAL_SECONDS:-120}"
mkdir -p storage

while true; do
  {
    echo "===== $(date --iso-8601=seconds) kdeck python goal runner ====="
    # .env は毎回読み直す。
    # 外で1回だけ読むと、RQDB4AI のトークンを更新しても、このプロセスを再起動するまで
    # 古い値を子プロセスへ渡し続ける。2026-09-13 に実際に起きた:
    # トークンをローテーションして .env は直したのに、31時間前に起動したこのループが
    # 古いトークンを持ち続け、enqueue が2分おきに 403 Invalid bearer token で落ち、
    # kdeck のゴールが1件も投入されない状態になっていた（ログには出るがサービスは active のまま）。
    load_env
    python3 -m app.commander_tool growth-cycle
  } >> storage/python_goal_runner.log 2>&1 || true
  sleep "$INTERVAL"
done
