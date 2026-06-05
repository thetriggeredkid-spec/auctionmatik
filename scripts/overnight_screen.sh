#!/usr/bin/env bash
# Auctionmatik — overnight screening wrapper (run by cron/launchd the night before a sale).
# 1) backs up the DB, 2) keeps the Mac awake, 3) batch deep-screens the soonest sale.
# Requires: Docker Postgres up. Carfax/vision auto-pull need this Mac logged in (Chrome).
#
#   ./scripts/overnight_screen.sh                 # next sale, triage→deep filter
#   ALL_DEEP=1 ./scripts/overnight_screen.sh      # deep every car
#   COMPS=1 ./scripts/overnight_screen.sh         # also scrape comps ($ Apify)
#   LIMIT=150 ./scripts/overnight_screen.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="$ROOT/venv/bin/python"
LOG_DIR="$ROOT/logs"; mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/overnight_$(date +%Y%m%d).log"

LIMIT="${LIMIT:-300}"
EXTRA=""
[[ "${ALL_DEEP:-0}" == "1" ]] && EXTRA="$EXTRA --all-deep"
[[ "${COMPS:-0}" == "1" ]] && EXTRA="$EXTRA --comps"
[[ -n "${MAX_DEEP:-}" ]] && EXTRA="$EXTRA --max-deep $MAX_DEEP"

{
  echo "===== overnight_screen $(date) ====="
  echo "[1/2] DB backup"
  ./scripts/backup_db.sh || echo "WARN: backup failed, continuing"
  echo "[2/2] batch deep-screen (next sale, limit $LIMIT$EXTRA)"
  # caffeinate keeps the Mac awake for the duration (-i idle, -s system)
  if command -v caffeinate >/dev/null 2>&1; then
    caffeinate -is "$PY" -m collector.screen_sale --next --limit "$LIMIT" $EXTRA
  else
    "$PY" -m collector.screen_sale --next --limit "$LIMIT" $EXTRA
  fi
  echo "===== done $(date) ====="
} >> "$LOG" 2>&1

echo "overnight_screen complete — log: $LOG"
