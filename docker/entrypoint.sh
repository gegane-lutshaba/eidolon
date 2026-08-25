#!/bin/sh
# Wait for Postgres, create/upgrade the schema (idempotent create_all — this is
# what registers the SAGE ledger + memory tables), then serve.
set -e

echo "eidolon: ensuring database schema at ${EIDOLON_DATABASE_URL:-<default>}"
attempt=0
until python -c "from eidolon.data.db import init_db; init_db()"; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "eidolon: database not ready after $attempt attempts — giving up" >&2
        exit 1
    fi
    echo "eidolon: database not ready (attempt $attempt), retrying in 2s…"
    sleep 2
done
echo "eidolon: schema ready."

exec uvicorn eidolon.api.app:app \
    --host "${EIDOLON_API_HOST:-0.0.0.0}" \
    --port "${EIDOLON_API_PORT:-8000}"
