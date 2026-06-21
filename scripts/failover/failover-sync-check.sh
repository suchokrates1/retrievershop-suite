#!/bin/bash
# Reverse sync po failoverze: Mikrus DB → minipc local postgres
# Cron minipc: */5 * * * * ~/backup/failover-sync-check.sh >> ~/backup/failover-sync.log 2>&1

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=db_freshness.sh
. "${SCRIPT_DIR}/db_freshness.sh"

WAHA_URL="http://localhost:3001"
WAHA_KEY="${WAHA_KEY:-}"
WAHA_TO="48697495755@c.us"

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

log()     { echo "${LOG_PREFIX} $*"; }
log_ok()  { echo "${LOG_PREFIX} OK: $*"; }
log_err() { echo "${LOG_PREFIX} ERROR: $*"; }

send_waha() {
    [ -n "$WAHA_KEY" ] || return 0
    curl -sf --max-time 10 \
        -X POST "${WAHA_URL}/api/sendText" \
        -H "Content-Type: application/json" \
        -H "X-Api-Key: ${WAHA_KEY}" \
        -d "{\"chatId\":\"${WAHA_TO}\",\"text\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$1"),\"session\":\"default\"}" \
        > /dev/null 2>&1
}

load_secrets() {
    local secrets_file="/home/suchokrates1/backup/failover-sync.secrets.env"
    if [ -f "$secrets_file" ]; then
        # shellcheck disable=SC1090
        source "$secrets_file"
        MIKRUS_PASS="${MIKRUS_PASS:-}"
        WAHA_KEY="${WAHA_KEY:-}"
    fi
    if [ -z "$MIKRUS_PASS" ]; then
        log_err "Brak MIKRUS_PASS (ustaw w failover-sync.secrets.env)"
        exit 1
    fi
}

clear_failover_flag() {
    docker exec -e PGPASSWORD="$MIKRUS_PASS" "$LOCAL_CONTAINER" \
        psql -h "$MIKRUS_HOST" -U "$MIKRUS_USER" -d "$MIKRUS_DB" \
        -c "UPDATE app_settings SET value='0' WHERE key='failover_sync_needed'" \
        > /dev/null 2>&1
}

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${LOCAL_CONTAINER}$"; then
    log "Kontener $LOCAL_CONTAINER nie działa - pomijam"
    exit 0
fi

load_secrets

SYNC_FLAG=$(docker exec -e PGPASSWORD="$MIKRUS_PASS" "$LOCAL_CONTAINER" \
    psql -h "$MIKRUS_HOST" -U "$MIKRUS_USER" -d "$MIKRUS_DB" \
    -tAc "SELECT value FROM app_settings WHERE key='failover_sync_needed'" 2>/dev/null || echo "")

if [ "$SYNC_FLAG" != "1" ]; then
    exit 0
fi

LOCAL_JSON=$(db_freshness_local_metrics)
MIKRUS_JSON=$(db_freshness_mikrus_metrics)
LOCAL_FMT=$(db_freshness_format "$LOCAL_JSON")
MIKRUS_FMT=$(db_freshness_format "$MIKRUS_JSON")

if db_freshness_metrics_equal "$LOCAL_JSON" "$MIKRUS_JSON"; then
    log "SKIP reverse sync: local == mikrus ($LOCAL_FMT)"
    clear_failover_flag && log_ok "Flaga wyczyszczona (bazy identyczne)"
    exit 0
fi

if db_freshness_local_is_newer "$LOCAL_JSON" "$MIKRUS_JSON"; then
    log "SKIP reverse sync: local nowszy od Mikrus"
    log "  local:  $LOCAL_FMT"
    log "  mikrus: $MIKRUS_FMT"
    clear_failover_flag && log_ok "Flaga failover_sync_needed wyczyszczona (sync odrzucony)"
    send_waha "⚠️ Reverse sync ODRZUCONY
Local nowszy — minipc zachowuje dane
local: $LOCAL_FMT
mikrus: $MIKRUS_FMT
$(date '+%Y-%m-%d %H:%M')" || true
    exit 0
fi

log "=== FAILOVER REVERSE SYNC: Mikrus DB → minipc local postgres ==="
log "  local:  $LOCAL_FMT"
log "  mikrus: $MIKRUS_FMT"
START_TIME=$(date +%s)

BACKUP_FILE="/home/suchokrates1/failover-pre-sync-backup.sql.gz"
log "Backup lokalnej bazy przed sync → $BACKUP_FILE"
docker exec "$LOCAL_CONTAINER" \
    pg_dump -U "$LOCAL_USER" -d "$LOCAL_DB" --clean --if-exists -x -O 2>/dev/null \
    | gzip > "$BACKUP_FILE" && log_ok "Backup OK" || log_err "Backup FAIL - kontynuuję mimo to"

log "Sync Mikrus DB → local postgres..."
ERRORS=$(docker exec -e PGPASSWORD="$MIKRUS_PASS" "$LOCAL_CONTAINER" bash -c "
    pg_dump -h $MIKRUS_HOST -U $MIKRUS_USER -d $MIKRUS_DB \\
        --clean --if-exists -x -O 2>/dev/null | \\
    psql -U $LOCAL_USER -d $LOCAL_DB -q -o /dev/null 2>&1
" | grep -v "^ERROR.*foreign key\|^ERROR.*cannot drop constraint\|^DETAIL\|^WARNING.*owner\|^NOTICE\|^HINT" || true)

ROWS=$(docker exec "$LOCAL_CONTAINER" \
    psql -U "$LOCAL_USER" -d "$LOCAL_DB" \
    -tAc "SELECT count(*) FROM allegro_offers" 2>/dev/null || echo "0")

ELAPSED=$(( $(date +%s) - START_TIME ))

if [ -n "$ROWS" ] && [ "$ROWS" -gt 0 ]; then
    log_ok "Reverse sync OK w ${ELAPSED}s | ${ROWS} ofert"
    clear_failover_flag && log_ok "Flaga failover_sync_needed wyczyszczona"
    [ -n "$ERRORS" ] && log "Błędy (ignorowane FK): $ERRORS"
    send_waha "✅ Reverse sync zakończony!
Czas: ${ELAPSED}s | Oferty: ${ROWS}
local po sync: $(db_freshness_format "$(db_freshness_local_metrics)")
$(date '+%Y-%m-%d %H:%M')" || true
else
    log_err "Reverse sync FAIL - brak wierszy w lokalnej bazie!"
    log_err "Błędy: $ERRORS"
    send_waha "❌ Reverse sync FAIL!
Sprawdź: ~/backup/failover-sync.log
Backup: $BACKUP_FILE
$(date '+%Y-%m-%d %H:%M')" || true
    exit 1
fi
