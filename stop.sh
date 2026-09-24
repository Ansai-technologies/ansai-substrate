#!/usr/bin/env bash
# Stop the local substrate. Spend data persists in the docker volume;
# your .env and .venv are untouched.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .office.pid ]; then
  pid="$(cat .office.pid)"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "office stopped (pid $pid)."
  fi
  rm -f .office.pid
fi

(cd gateway && docker compose down)
echo "substrate stopped."
