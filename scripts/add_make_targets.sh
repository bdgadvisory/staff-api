#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Ensure dev_env exists (no-op if already there)
if [[ ! -f scripts/dev_env.sh ]]; then
  echo "scripts/dev_env.sh not found; create it first (run the dev_env script block)."
  exit 1
fi

# Append targets if missing
if ! grep -q '^dev:' Makefile 2>/dev/null; then
  cat >> Makefile <<'MAKE'

.PHONY: venv install dev migrate tick

venv:
python3 -m venv .venv

install:
. .venv/bin/activate && pip install -U pip && pip install -r requirements.txt

dev:
. .venv/bin/activate && . scripts/dev_env.sh && python -m uvicorn main:app --reload --port 8000

migrate:
. .venv/bin/activate && . scripts/dev_env.sh && python scripts/migrate.py

tick:
curl -s -X POST http://127.0.0.1:8000/internal/reminders/tick \
  -H "X-Reminders-Tick-Secret: $$REMINDERS_TICK_SECRET" | python3 -m json.tool
MAKE
else
  echo "Makefile already has a dev: target; skipping append."
fi

git add Makefile
git commit -m "Add Makefile targets for local dev/migrate/tick" || true
git push public main
