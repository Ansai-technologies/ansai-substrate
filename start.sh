#!/usr/bin/env bash
# Ansai substrate — one-command local startup.
#   1. checks prerequisites (python3, docker)
#   2. creates .venv and installs requirements (first run only)
#   3. ensures gateway/.env exists with your keys
#   4. starts the LiteLLM gateway (docker compose: litellm + postgres)
#   5. waits for health, then runs the Baraza 2.0 spike end to end
#
# Usage: ./start.sh
# Stop everything: ./stop.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/5 prerequisites =="
command -v python3 >/dev/null || { echo "need python3"; exit 1; }
command -v docker >/dev/null || { echo "need docker (Docker Desktop). install it, then re-run."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "need 'docker compose' plugin"; exit 1; }
echo "ok"

echo "== 2/5 python venv =="
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  echo "installed"
else
  echo "exists, skipping"
fi

echo "== 3/5 gateway env =="
if [ ! -f gateway/.env ]; then
  cp gateway/.env.example gateway/.env
  echo "created gateway/.env from the example."
fi
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

echo "== 4/5 gateway up =="
(cd gateway && docker compose up -d)
echo -n "waiting for gateway health"
for i in $(seq 1 30); do
  if curl -sf http://localhost:4000/health >/dev/null 2>&1; then echo " ok"; break; fi
  echo -n "."; sleep 2
  if [ "$i" = 30 ]; then echo ""; echo "gateway did not become healthy; check: (cd gateway && docker compose logs)"; exit 1; fi
done

echo "== 5/5 baraza spike =="
export GATEWAY_URL="${GATEWAY_URL:-http://localhost:4000}"
export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-ansai-dev-local}"
.venv/bin/python agents/baraza/run_weekly_cycle.py

echo ""
echo "done. gateway: http://localhost:4000  (UI: http://localhost:4000/ui)"
echo "stop: ./stop.sh"
