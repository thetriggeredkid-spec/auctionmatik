#!/usr/bin/env bash
# Auctionmatik — Postgres backup
# Dumps the database from the running Docker container to a timestamped, gzipped
# file in backups/, then prunes old copies. Safe to run on a schedule (cron/launchd).
#
#   ./scripts/backup_db.sh                 # one backup, keep last 14
#   KEEP=30 ./scripts/backup_db.sh         # keep last 30
#
# Restore (see scripts/restore_db.sh):
#   gunzip -c backups/<file>.sql.gz | docker exec -i auctionmatik_db psql -U <user> -d <db>

set -euo pipefail

# Resolve repo root (this script lives in scripts/) and load .env
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a; . ./.env; set +a
fi

CONTAINER="${DB_CONTAINER:-auctionmatik_db}"
DB="${POSTGRES_DB:-auctionmatik}"
USER="${POSTGRES_USER:-auctionmatik}"
KEEP="${KEEP:-14}"
BACKUP_DIR="$ROOT/backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/auctionmatik_${STAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

# Container must be running
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "[backup] ERROR: container '$CONTAINER' is not running. Start it: docker compose up -d" >&2
  exit 1
fi

echo "[backup] dumping $DB from $CONTAINER → $OUT"
# --clean --if-exists makes the dump restorable over an existing DB
if docker exec "$CONTAINER" pg_dump -U "$USER" -d "$DB" --clean --if-exists 2>/dev/null | gzip > "$OUT"; then
  : # ok
else
  echo "[backup] ERROR: pg_dump failed; removing partial file" >&2
  rm -f "$OUT"
  exit 1
fi

# Sanity: non-trivial size
SIZE=$(wc -c < "$OUT" | tr -d ' ')
if [[ "$SIZE" -lt 1000 ]]; then
  echo "[backup] ERROR: dump suspiciously small (${SIZE} bytes); removing" >&2
  rm -f "$OUT"
  exit 1
fi

echo "[backup] wrote $(du -h "$OUT" | cut -f1) ($SIZE bytes)"

# Prune: keep the newest $KEEP
COUNT=$(ls -1 "$BACKUP_DIR"/auctionmatik_*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
if [[ "$COUNT" -gt "$KEEP" ]]; then
  ls -1t "$BACKUP_DIR"/auctionmatik_*.sql.gz | tail -n +$((KEEP + 1)) | while read -r old; do
    echo "[backup] pruning $(basename "$old")"
    rm -f "$old"
  done
fi

echo "[backup] done — $(ls -1 "$BACKUP_DIR"/auctionmatik_*.sql.gz | wc -l | tr -d ' ') backup(s) retained (keep=$KEEP)"
