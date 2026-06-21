#!/bin/bash
# Porównaj metryki local postgres vs Mikrus — alert gdy rozjazd.
# Cron: 10 3 * * * (po backup) lub wywołanie z mikrus-db-sync.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=db_freshness.sh
. "${SCRIPT_DIR}/db_freshness.sh"

WAHA_URL="http://localhost:3001"
WAHA_KEY="${WAHA_KEY:-}"
WAHA_TO="48697495755@c.us"
QUIET=0

for arg in "$@"; do
    [ "$arg" = "--quiet" ] && QUIET=1
done

log() { [ "$QUIET" -eq 0 ] && echo "[$(date '+%H:%M:%S')] $*"; }

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
    [ -f "$secrets_file" ] && source "$secrets_file"
    MIKRUS_PASS="${MIKRUS_PASS:-}"
    WAHA_KEY="${WAHA_KEY:-}"
}

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${LOCAL_CONTAINER}$"; then
    log "Postgres nie działa - pomijam verify"
    exit 0
fi

load_secrets
[ -z "$MIKRUS_PASS" ] && { log "Brak MIKRUS_PASS"; exit 1; }

LOCAL_JSON=$(db_freshness_local_metrics)
MIKRUS_JSON=$(db_freshness_mikrus_metrics)

if [ -z "$LOCAL_JSON" ] || [ -z "$MIKRUS_JSON" ]; then
    log "Nie udało się odczytać metryk"
    exit 1
fi

if db_freshness_metrics_equal "$LOCAL_JSON" "$MIKRUS_JSON"; then
    log "OK: local == mikrus ($(db_freshness_format "$LOCAL_JSON"))"
    exit 0
fi

LOCAL_FMT=$(db_freshness_format "$LOCAL_JSON")
MIKRUS_FMT=$(db_freshness_format "$MIKRUS_JSON")
log "ROZJAZD local vs mikrus:"
log "  local:  $LOCAL_FMT"
log "  mikrus: $MIKRUS_FMT"

send_waha "⚠️ Mikrus DB rozjazd z minipc
local:  $LOCAL_FMT
mikrus: $MIKRUS_FMT
Sprawdź mikrus-db-sync / backup.log
$(date '+%Y-%m-%d %H:%M')" || true

exit 1
