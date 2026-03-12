# Staff API Runbook (MVP)

## Deploy
- Push to `main` triggers Cloud Build -> Cloud Run deploy automatically.

## Auth
- Cloud Run is not public; requests need an identity token:
  - `./scripts/get_token.sh`

## Common ops
- `make health`
- `make db-check`
- `make approvals-pending`
- `make approval ID=<uuid>`
- `make message ID=<uuid>`
- `make approve ID=<uuid>`
- `make reject ID=<uuid> NOTE='...'`

## Scribe
- `make scribe TOPIC='...' ANGLE='...'` (creates an approval)

## Migrations (local only)
- Requires env vars set locally:
  - INSTANCE_CONNECTION_NAME, DB_NAME, DB_USER, DB_PASSWORD
- Run: `make migrate`
