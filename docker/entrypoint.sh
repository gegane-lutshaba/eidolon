#!/bin/sh
# Wait for Postgres, create/upgrade the schema (idempotent create_all — this is
# what registers the SAGE ledger + memory tables), then serve.
set -e

# Secure by default: a container binds 0.0.0.0, so with no operator token the
# control plane would be reachable by anyone who can reach the port. Generate an
# admin token once, keep it in the data volume, and print it. Opt out only with
# EIDOLON_OPEN_MODE=1 (demos), or set your own EIDOLON_ADMIN_TOKEN.
if [ -z "${EIDOLON_ADMIN_TOKEN}${EIDOLON_AUDIT_TOKEN}" ] && [ "${EIDOLON_OPEN_MODE}" != "1" ] \
   && [ "${EIDOLON_OPEN_MODE}" != "true" ]; then
    token_file="${EIDOLON_DATA_DIR:-/data}/.admin_token"
    if [ -s "$token_file" ]; then
        EIDOLON_ADMIN_TOKEN="$(cat "$token_file")"
    else
        EIDOLON_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
        if (umask 077 && printf '%s' "$EIDOLON_ADMIN_TOKEN" > "$token_file") 2>/dev/null; then
            echo "eidolon: generated an operator admin token (saved to $token_file)"
        else
            echo "eidolon: generated an operator admin token (not persisted: $token_file unwritable)"
        fi
    fi
    export EIDOLON_ADMIN_TOKEN
    echo "eidolon: ================================================================"
    echo "eidolon:  operator admin token: $EIDOLON_ADMIN_TOKEN"
    echo "eidolon:  sign in to the operator console at /login with it."
    echo "eidolon:  set EIDOLON_ADMIN_TOKEN yourself to choose one."
    echo "eidolon: ================================================================"
fi

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
