#!/usr/bin/env bash
# Restore an EIDOLON Postgres backup produced by deploy/backup.sh.
#
#   ./deploy/restore.sh backups/eidolon-20260826T030000Z.sql.gz
#
# DESTRUCTIVE: drops and recreates the public schema before loading. Requires
# an explicit confirmation.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="${1:-}"
[[ -f "$FILE" ]] || { echo "usage: $0 <backup.sql.gz>" >&2; exit 1; }

DEPLOY="docker compose -f docker-compose.deploy.yml"
echo "!! This will OVERWRITE the current eidolon database with $FILE"
read -r -p "Type 'restore' to proceed: " ans
[[ "$ans" == "restore" ]] || { echo "aborted"; exit 1; }

echo "==> resetting schema"
$DEPLOY exec -T db psql -U eidolon -d eidolon -c \
	"DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "==> loading $FILE"
gunzip -c "$FILE" | $DEPLOY exec -T db psql -U eidolon -d eidolon

echo "==> restarting app"
$DEPLOY restart eidolon
echo "==> done. Verify ledger integrity: make deploy-verify"
