#!/usr/bin/env bash
# Wspolne helpery dla skryptow failover VPS.

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

log()      { echo "[$(timestamp)] ${LOG_PREFIX:-[failover]} $*"; }
log_ok()   { echo "[$(timestamp)] ${LOG_PREFIX:-[failover]} OK: $*"; }
log_err()  { echo "[$(timestamp)] ${LOG_PREFIX:-[failover]} ERROR: $*"; }
log_warn() { echo "[$(timestamp)] ${LOG_PREFIX:-[failover]} WARN: $*"; }

load_secrets() {
    local secrets_file="$1"
    if [ ! -f "$secrets_file" ]; then
        log_err "Brak $secrets_file"
        exit 1
    fi
    # shellcheck source=/dev/null
    . "$secrets_file"
}

json_string() {
    python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$1"
}

send_messenger() {
    local msg="$1"
    local messenger_api="https://graph.facebook.com/v22.0/me/messages"

    if [ -z "${MESSENGER_TOKEN:-}" ] || [ -z "${MESSENGER_RECIPIENT:-}" ]; then
        log_warn "Messenger: brak tokenu lub odbiorcy"
        return 1
    fi

    curl -sf --max-time 10 \
        -X POST "$messenger_api" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${MESSENGER_TOKEN}" \
        -d "{\"recipient\":{\"id\":\"${MESSENGER_RECIPIENT}\"},\"messaging_type\":\"UPDATE\",\"message\":{\"text\":$(json_string "$msg")}}" \
        > /dev/null 2>&1
}