#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
: "${KDECK_HOST:=0.0.0.0}"
: "${KDECK_PORT:=18301}"
exec python3 -m uvicorn app.main:app --host "$KDECK_HOST" --port "$KDECK_PORT"
