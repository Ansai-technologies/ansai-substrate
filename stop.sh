#!/usr/bin/env bash
# Stop the local substrate (gateway + postgres). Spend data persists in the
# docker volume; your .env and .venv are untouched.
set -euo pipefail
cd "$(dirname "$0")/gateway"
docker compose down
echo "substrate stopped."
