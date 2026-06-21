#!/bin/bash
# Sync bazy magazyn: minipc local postgres → Mikrus shared DB (failover standby)
# Wywoływany z backup.sh codziennie o 03:00

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=db_freshness.sh
. "${SCRIPT_DIR}/db_freshness.sh"

WAHA_URL="http://localhost:3001"
WAHA_KEY="${WAHA_KEY:-}"
WAHA_TO="48697495755@c.us"

log()     { echo "[$(date '+%H:%M:%S')] $*"; }
log_ok()  { echo "[$(date '+%H:%M:%S')] OK: $*"; }
log_err() { echo "[$(date '+%H:%M:%S')] ERROR: $*"; }
log_warn(){ echo "[$(date '+%H:%M:%S')] WARN: $*"; }

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
        log_err "Brak MIKRUS_PASS w failover-sync.secrets.env"
        exit 1
    fi
}

log "--- Sync magazyn -> Mikrus shared DB ($MIKRUS_HOST) ---"

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${LOCAL_CONTAINER}$"; then
    log_warn "retrievershop-postgres nie działa - sync pominięty"
    exit 1
fi

load_secrets

if ! docker exec -e PGPASSWORD="$MIKRUS_PASS" "$LOCAL_CONTAINER" \
    psql -h "$MIKRUS_HOST" -U "$MIKRUS_USER" -d "$MIKRUS_DB" -tAc "SELECT 1" 2>/dev/null | grep -q 1; then
    log_err "Brak połączenia z $MIKRUS_HOST!"
    exit 1
fi

log "  Połączenie OK, dump + restore..."
START=$(date +%s)

ERRORS=$(docker exec -e PGPASSWORD="$MIKRUS_PASS" "$LOCAL_CONTAINER" bash -c \
    "pg_dump -U $LOCAL_USER -d $LOCAL_DB --clean --if-exists -x -O 2>/dev/null | \
     psql -h $MIKRUS_HOST -U $MIKRUS_USER -d $MIKRUS_DB -q -o /dev/null 2>&1" \
    | grep -v "^ERROR.*foreign key\|^DETAIL" || true)

ELAPSED=$(( $(date +%s) - START ))
ROWS=$(docker exec -e PGPASSWORD="$MIKRUS_PASS" "$LOCAL_CONTAINER" \
    psql -h "$MIKRUS_HOST" -U "$MIKRUS_USER" -d "$MIKRUS_DB" \
    -tAc "SELECT count(*) FROM allegro_offers" 2>/dev/null | tr -d ' ')

if [ -n "$ROWS" ] && [ "$ROWS" -gt 0 ]; then
    [ -n "$ERRORS" ] && log_warn "Sync z błędami FK: $ERRORS"
    log_ok "Sync OK w ${ELAPSED}s | ${ROWS} ofert na Mikrus"
    # Weryfikacja spójności po sync
    if [ -x "${SCRIPT_DIR}/mikrus-db-verify.sh" ]; then
        bash "${SCRIPT_DIR}/mikrus-db-verify.sh" --quiet || true
    fi
    exit 0
fi

log_err "Sync FAILED - brak danych w db_robert136 po restore!"
send_waha "❌ Mikrus forward sync FAIL
Sprawdź backup.log / mikrus-db-sync.sh
$(date '+%Y-%m-%d %H:%M')" || true
exit 1
