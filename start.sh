#!/usr/bin/env bash
# Ansai substrate — one-command local startup.
#   1. checks prerequisites (python3, docker)
#   2. creates .venv and installs requirements (first run only)
#   3. ensures gateway/.env exists with your keys
#   4. starts the LiteLLM gateway (docker compose: litellm + postgres)
#   5. starts the Office UI (visualization + chat) on :8080, opens a browser tab
#   6. runs the Baraza 2.0 spike end to end (its events appear in the office)
#
# Usage: ./start.sh
# Stop everything: ./stop.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/6 prerequisites =="
# pick a working python: python3 on mac/linux, python on windows.
# (windows ships a fake python3.exe stub that opens the Store — verify the binary runs)
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" --version >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "need python3: https://www.python.org/downloads/ (tick 'Add to PATH'), then re-run."; exit 1; }
echo "python: $PY ($("$PY" --version 2>&1))"
command -v docker >/dev/null || { echo "need docker (Docker Desktop). install it, start it, then re-run."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "need 'docker compose' plugin"; exit 1; }
echo "ok"

echo "== 2/6 python venv =="
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  FRESH_VENV=1
else
  echo "exists, skipping"
fi
# venv layout differs per OS: .venv/bin (mac/linux) vs .venv/Scripts (windows)
if [ -d .venv/bin ]; then VBIN=.venv/bin; else VBIN=.venv/Scripts; fi
if [ "${FRESH_VENV:-0}" = 1 ]; then
  "$VBIN/pip" install -q --upgrade pip
  "$VBIN/pip" install -q -r requirements.txt
  echo "installed"
fi

echo "== 3/6 gateway env =="
if [ ! -f gateway/.env ]; then
  cp gateway/.env.example gateway/.env
  echo "created gateway/.env from the example."
fi
# normalize CRLF (e.g. .env written by PowerShell) so sourced values carry no trailing \r
sed -i.bak 's/\r$//' gateway/.env && rm -f gateway/.env.bak
# shellcheck disable=SC1091
set -a; source gateway/.env; set +a
if [ -z "${DEEPSEEK_API_KEY:-}" ] || [ -z "${GEMINI_API_KEY:-}" ]; then
  echo ""
  echo "STOP: paste your keys into gateway/.env first:"
  echo "  DEEPSEEK_API_KEY=...   (platform.deepseek.com -> API keys)"
  echo "  GEMINI_API_KEY=...     (aistudio.google.com -> Get API key)"
  echo "then re-run ./start.sh"
  exit 1
fi
echo "keys present"

echo "== 4/6 gateway up =="
(cd gateway && docker compose up -d)
echo -n "waiting for gateway health"
for i in $(seq 1 30); do
  if curl -sf http://localhost:4000/health >/dev/null 2>&1; then echo " ok"; break; fi
  echo -n "."; sleep 2
  if [ "$i" = 30 ]; then echo ""; echo "gateway did not become healthy; check: (cd gateway && docker compose logs)"; exit 1; fi
done

echo "== 5/6 office UI =="
export GATEWAY_URL="${GATEWAY_URL:-http://localhost:4000}"
export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-ansai-dev-local}"
export OFFICE_URL="http://localhost:8080"
if [ -f .office.pid ] && kill -0 "$(cat .office.pid)" 2>/dev/null; then
  echo "office already running (pid $(cat .office.pid))"
else
  "$VBIN/python" -m uvicorn office.server:app --host 127.0.0.1 --port 8080 \
    >/tmp/ansai-office.log 2>&1 &
  echo $! > .office.pid
  echo -n "waiting for office"
  for i in $(seq 1 20); do
    if curl -sf http://localhost:8080/api/health >/dev/null 2>&1; then echo " ok"; break; fi
    echo -n "."; sleep 1
    if [ "$i" = 20 ]; then echo ""; echo "office did not start; see /tmp/ansai-office.log"; exit 1; fi
  done
fi
# best-effort browser tab; never fails the script (headless-safe)
( xdg-open http://localhost:8080 >/dev/null 2>&1 \
  || open http://localhost:8080 >/dev/null 2>&1 \
  || powershell.exe -c "start http://localhost:8080" >/dev/null 2>&1 \
  || true ) &
echo "office: http://localhost:8080"

echo "== 6/6 baraza spike =="
"$VBIN/python" agents/baraza/run_weekly_cycle.py

echo ""
echo "done."
echo "  gateway: http://localhost:4000  (UI: http://localhost:4000/ui)"
echo "  office:  http://localhost:8080  (visualization + chat)"
echo "stop: ./stop.sh"
