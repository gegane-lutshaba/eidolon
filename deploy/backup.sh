#!/usr/bin/env bash
# Back up the EIDOLON Postgres database (memory + the attestation ledger) to a
# timestamped, gzipped pg_dump. Run from the repo root, ideally via cron:
#
#   0 3 * * *  cd /opt/eidolon && ./deploy/backup.sh >> /var/log/eidolon-backup.log 2>&1
#
# Restore with deploy/restore.sh <file>.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${EIDOLON_BACKUP_DIR:-./backups}"
KEEP="${EIDOLON_BACKUP_KEEP:-14}"
mkdir -p "$OUT_DIR"

DEPLOY="docker compose -f docker-compose.deploy.yml"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT_DIR/eidolon-$STAMP.sql.gz"

echo "==> dumping database -> $FILE"
$DEPLOY exec -T db pg_dump -U eidolon -d eidolon | gzip > "$FILE"

# Verify the archive is non-empty and well-formed gzip.
gzip -t "$FILE"
echo "==> ok ($(du -h "$FILE" | cut -f1))"

# Retention: keep the newest $KEEP dumps.
ls -1t "$OUT_DIR"/eidolon-*.sql.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "==> retained newest $KEEP backups in $OUT_DIR"
