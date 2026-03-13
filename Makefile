SHELL := /bin/bash

BASE ?= https://staff-api-867841687803.us-central1.run.app
TOKEN := $(shell ./scripts/get_token.sh)

.PHONY: help approvals-pending approval message approve reject interview-ask interview-answer scribe

help:
	@echo "make approvals-pending"
	@echo "make approval ID=<uuid>"
	@echo "make message ID=<uuid>"
	@echo "make approve ID=<uuid>"
	@echo "make reject ID=<uuid> NOTE='...'"
	@echo "make interview-ask ID=<uuid> Q1='...' Q2='...' Q3='...'"
	@echo "make interview-answer ID=<uuid> A1='...' A2='...' A3='...' NOTE='...'"
	@echo "make scribe TOPIC='...' ANGLE='...'"

approvals-pending:
	@curl -sS "$(BASE)/approvals?status=pending&limit=20" -H "Authorization: Bearer $(TOKEN)" | python3 -m json.tool | head -n 200

approval:
	@if [ -z "$(ID)" ]; then echo "Set ID=<approval_id>"; exit 2; fi
	@curl -sS "$(BASE)/approvals/$(ID)" -H "Authorization: Bearer $(TOKEN)" | python3 -m json.tool | head -n 240

message:
	@if [ -z "$(ID)" ]; then echo "Set ID=<approval_id>"; exit 2; fi
	@curl -sS "$(BASE)/approvals/$(ID)/message" -H "Authorization: Bearer $(TOKEN)" | python3 -m json.tool | head -n 200

approve:
	@if [ -z "$(ID)" ]; then echo "Set ID=<approval_id>"; exit 2; fi
	@curl -sS -X POST "$(BASE)/approvals/$(ID)/action" -H "Authorization: Bearer $(TOKEN)" -H "Content-Type: application/json" -d '{"action":"approve"}' | python3 -m json.tool | head -n 120

reject:
	@if [ -z "$(ID)" ]; then echo "Set ID=<approval_id>"; exit 2; fi
	@if [ -z "$(NOTE)" ]; then echo "Set NOTE='...'"; exit 2; fi
	@curl -sS -X POST "$(BASE)/approvals/$(ID)/action" -H "Authorization: Bearer $(TOKEN)" -H "Content-Type: application/json" -d '{"action":"reject","notes":"$(NOTE)"}' | python3 -m json.tool | head -n 220

interview-ask:
	@if [ -z "$(ID)" ]; then echo "Set ID=<approval_id>"; exit 2; fi
	@if [ -z "$(Q1)" ]; then echo "Set Q1='...'"; exit 2; fi
	@curl -sS -X POST "$(BASE)/approvals/$(ID)/action" -H "Authorization: Bearer $(TOKEN)" -H "Content-Type: application/json" -d '{"action":"interview","questions":["$(Q1)","$(Q2)","$(Q3)"]}' | python3 -m json.tool | head -n 240

interview-answer:
	@if [ -z "$(ID)" ]; then echo "Set ID=<approval_id>"; exit 2; fi
	@if [ -z "$(A1)" ]; then echo "Set A1='...'"; exit 2; fi
	@curl -sS -X POST "$(BASE)/approvals/$(ID)/action" -H "Authorization: Bearer $(TOKEN)" -H "Content-Type: application/json" -d '{"action":"interview","answers":{"1":"$(A1)","2":"$(A2)","3":"$(A3)"},"notes":"$(NOTE)"}' | python3 -m json.tool | head -n 260

scribe:
	@if [ -z "$(TOPIC)" ]; then echo "Set TOPIC='...'"; exit 2; fi
	@curl -sS -X POST "$(BASE)/scribe/linkedin" -H "Authorization: Bearer $(TOKEN)" -H "Content-Type: application/json" -d '{"topic":"$(TOPIC)","angle":"$(ANGLE)","num_sources":5,"voice":true,"request_approval":true}' | python3 -c 'import sys,json; d=json.load(sys.stdin); print("approval_id=", d.get("approval_id")); print(d.get("approval_message_text","")[:900])'

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
