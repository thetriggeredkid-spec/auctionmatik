#!/usr/bin/env bash
# Auctionmatik — restore the database from a backup made by backup_db.sh.
#
#   ./scripts/restore_db.sh                         # restore the most recent backup
#   ./scripts/restore_db.sh backups/auctionmatik_20260605_010000.sql.gz
#
# WARNING: this overwrites the current database (the dump is --clean --if-exists).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then set -a; . ./.env; set +a; fi

CONTAINER="${DB_CONTAINER:-auctionmatik_db}"
DB="${POSTGRES_DB:-auctionmatik}"
USER="${POSTGRES_USER:-auctionmatik}"

FILE="${1:-}"
if [[ -z "$FILE" ]]; then
  FILE=$(ls -1t "$ROOT"/backups/auctionmatik_*.sql.gz 2>/dev/null | head -1 || true)
fi
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "[restore] no backup file found. Pass one explicitly." >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "[restore] ERROR: container '$CONTAINER' is not running." >&2
  exit 1
fi

echo "[restore] About to OVERWRITE database '$DB' from: $(basename "$FILE")"
read -r -p "[restore] Type 'yes' to continue: " confirm
[[ "$confirm" == "yes" ]] || { echo "[restore] aborted."; exit 1; }

gunzip -c "$FILE" | docker exec -i "$CONTAINER" psql -U "$USER" -d "$DB" -v ON_ERROR_STOP=1
echo "[restore] done — restored from $(basename "$FILE")"
