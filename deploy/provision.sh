#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu/Debian VPS to run EIDOLON.
#
#   curl -fsSL <repo>/deploy/provision.sh | bash        # or run from a clone
#   sudo bash deploy/provision.sh
#
# Idempotent: installs Docker if missing, generates a .env with strong secrets
# on first run (never overwrites an existing one), and brings the stack up.
# Set EIDOLON_DOMAIN in the environment to also start Caddy (auto-HTTPS).
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_DIR"
echo "==> EIDOLON provision in $REPO_DIR"

# --- Docker ------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
	echo "==> installing Docker"
	curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
	echo "!! Docker Compose plugin not found. Install docker-compose-plugin and re-run." >&2
	exit 1
fi

# --- .env with generated secrets --------------------------------------
gen() { openssl rand -hex 32; }
if [[ ! -f .env ]]; then
	echo "==> generating .env with fresh secrets (saved once; keep it safe)"
	cp .env.example .env
	# Fill blanks with strong random values.
	sed -i "s|^EIDOLON_DB_PASSWORD=.*|EIDOLON_DB_PASSWORD=$(gen)|" .env
	sed -i "s|^EIDOLON_ADMIN_TOKEN=.*|EIDOLON_ADMIN_TOKEN=$(gen)|" .env
	sed -i "s|^EIDOLON_AUDIT_TOKEN=.*|EIDOLON_AUDIT_TOKEN=$(gen)|" .env
	if [[ -n "${EIDOLON_DOMAIN:-}" ]]; then
		sed -i "s|^EIDOLON_DOMAIN=.*|EIDOLON_DOMAIN=${EIDOLON_DOMAIN}|" .env
		sed -i "s|^EIDOLON_SESSION_COOKIE_SECURE=.*|EIDOLON_SESSION_COOKIE_SECURE=true|" .env
	fi
else
	echo "==> .env already exists; leaving it untouched"
fi

# --- bring it up -------------------------------------------------------
DEPLOY="docker compose -f docker-compose.deploy.yml"
if [[ -n "${EIDOLON_DOMAIN:-}" ]]; then
	echo "==> starting stack + Caddy (auto-HTTPS for ${EIDOLON_DOMAIN})"
	$DEPLOY --profile tls up -d --build
else
	echo "==> starting stack (no domain set; app on :\${EIDOLON_PORT:-8000}, no TLS)"
	$DEPLOY up -d --build
fi

echo
echo "==> done. Tokens are in $REPO_DIR/.env :"
grep -E "^EIDOLON_(ADMIN|AUDIT)_TOKEN=" .env | sed 's/=/ = /'
echo "    Sign in at the admin token; the auditor token is read-only."
