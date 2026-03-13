#!/usr/bin/env bash
# Usage:
#   source scripts/dev_env.sh
#
# Requires:
#   - gcloud authenticated
#   - access to project staff-490001
#   - Secret Manager secret: DB_PASSWORD

set -euo pipefail

export INSTANCE_CONNECTION_NAME="${INSTANCE_CONNECTION_NAME:-staff-490001:us-central1:staff-pg}"
export DB_USER="${DB_USER:-staffapp}"
export DB_NAME="${DB_NAME:-postgres}"

# Pull DB password from Secret Manager (avoid printing it)
if [[ -z "${DB_PASSWORD:-}" ]]; then
  export DB_PASSWORD="$(gcloud secrets versions access latest --secret DB_PASSWORD --project staff-490001)"
fi

# Tick secret for local dev (override as needed)
export REMINDERS_TICK_SECRET="${REMINDERS_TICK_SECRET:-testsecret}"

echo "Loaded dev env:"
echo "  INSTANCE_CONNECTION_NAME=$INSTANCE_CONNECTION_NAME"
echo "  DB_NAME=$DB_NAME"
echo "  DB_USER=$DB_USER"
echo "  REMINDERS_TICK_SECRET=[set]"
