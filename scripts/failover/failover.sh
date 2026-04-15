#!/usr/bin/env bash
# VPS Failover Script - magazyn.retrievershop.pl
# Cron: * * * * * /home/suchokrates1/failover/failover.sh >> /home/suchokrates1/failover/failover.log 2>&1
#
# Logika:
#   - Co minute sprawdza minipc przez Tailscale
#   - Po 2 kolejnych failach (~2 min) aktywuje failover:
#     1. Start magazyn-failover container (port 8000, Mikrus DB)
#     2. Dodaje route do cloudflared VPS config
#     3. Cloudflare API: dodaje CNAME magazyn -> VPS tunnel (override wildcard)
#   - Gdy minipc wraca: cofa wszystko w odwrotnej kolejnosci
#   - Maintenance window 03:00-03:45: pomija aktywacje (backup/rebuild na minipc)

set -uo pipefail

FAILOVER_DIR="/home/suchokrates1/failover"
STATE_FILE="$FAILOVER_DIR/state"
FAIL_COUNT_FILE="$FAILOVER_DIR/fail_count"
CF_RECORD_FILE="$FAILOVER_DIR/cf_record_id"

# --- flock: zapobieganie rownoleglemu uruchomieniu z crona ---
LOCK_FILE="$FAILOVER_DIR/failover.lock"
exec 200>"$LOCK_FILE"
flock -n 200 || { echo "[$(date '+%Y-%m-%d %H:%M:%S')] Inny failover.sh juz dziala - pomijam"; exit 0; }

MINIPC_TAILSCALE="100.110.194.46"
# Normalny check: publiczny URL przez Cloudflare tunnel minipc
MINIPC_CHECK_URL="https://magazyn.retrievershop.pl/healthz"
# Recovery check (gdy failover aktywny): dedykowany URL tylko minipc, nie overridowany
MINIPC_RECOVERY_URL="https://minipc-check.retrievershop.pl/healthz"
REQUIRED_FAILS=2

CF_TOKEN="***CF_TOKEN_REDACTED***"
ZONE_ID="***ZONE_ID_REDACTED***"
VPS_TUNNEL_CNAME="59d6c42e-f783-448d-8302-905acb1bab14.cfargotunnel.com"
CLOUDFLARED_CONFIG="/etc/cloudflared/config.yml"

WAHA_URL="http://${MINIPC_TAILSCALE}:3001"
WAHA_KEY="***WAHA_KEY_REDACTED***"
WAHA_TO="***WAHA_TO_REDACTED***"

# Messenger fallback (WAHA na minipc jest niedostepna gdy minipc pada)
MESSENGER_TOKEN="***MESSENGER_TOKEN_REDACTED***"
MESSENGER_RECIPIENT="***MESSENGER_RECIPIENT_REDACTED***"
MESSENGER_API="https://graph.facebook.com/v22.0/me/messages"

MIKRUS_DSN="***MIKRUS_DSN_REDACTED***"
SNAPSHOT_FILE="$FAILOVER_DIR/snapshot.json"
ACTIVATE_TIME_FILE="$FAILOVER_DIR/activate_time"

log()      { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
log_ok()   { echo "[$(date '+%Y-%m-%d %H:%M:%S')] OK: $*"; }
log_err()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*"; }

get_state()      { cat "$STATE_FILE" 2>/dev/null || echo "normal"; }
set_state()      { echo "$1" > "$STATE_FILE"; }
get_fail_count() { cat "$FAIL_COUNT_FILE" 2>/dev/null || echo 0; }
set_fail_count() { echo "$1" > "$FAIL_COUNT_FILE"; }

check_minipc() {
    # state=active -> recovery check: Tailscale (primary), CF minipc-check (fallback)
    # state=normal -> publiczny URL magazyn (przez wildcard -> minipc tunnel)
    if [ "$(get_state)" = "active" ]; then
        # Primary: Tailscale bezposrednio do minipc (omija Cloudflare)
        curl -sf --connect-timeout 5 --max-time 10 \
            "http://${MINIPC_TAILSCALE}:8000/healthz" > /dev/null 2>&1 && return 0
        # Fallback: CF tunnel minipc-check (wymaga public hostname w CF Zero Trust)
        curl -sf --connect-timeout 5 --max-time 10 \
            "$MINIPC_RECOVERY_URL" > /dev/null 2>&1 && return 0
        return 1
    else
        curl -sf --connect-timeout 5 --max-time 10 \
            "$MINIPC_CHECK_URL" > /dev/null 2>&1
    fi
}

send_waha() {
    local msg="$1"
    curl -sf --max-time 10 \
        -X POST "${WAHA_URL}/api/sendText" \
        -H "Content-Type: application/json" \
        -H "X-Api-Key: ${WAHA_KEY}" \
        -d "{\"chatId\":\"${WAHA_TO}\",\"text\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$msg"),\"session\":\"default\"}" \
        > /dev/null 2>&1 && return 0 || return 1
}

send_messenger() {
    local msg="$1"
    curl -sf --max-time 10 \
        -X POST "$MESSENGER_API" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${MESSENGER_TOKEN}" \
        -d "{\"recipient\":{\"id\":\"${MESSENGER_RECIPIENT}\"},\"messaging_type\":\"UPDATE\",\"message\":{\"text\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$msg")}}" \
        > /dev/null 2>&1 && return 0 || return 1
}

notify() {
    # Wysyla powiadomienie: najpierw WAHA, potem Messenger jako fallback
    local msg="$1"
    if send_waha "$msg"; then
        log_ok "WAHA alert wyslany"
    elif send_messenger "$msg"; then
        log_ok "Messenger alert wyslany (WAHA niedostepna)"
    else
        log_warn "Brak kanalow powiadomien - alert tylko w logu"
    fi
}

cf_add_magazyn_cname() {
    local result
    result=$(curl -sf -X POST \
        "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
        -H "Authorization: Bearer ${CF_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"type\":\"CNAME\",\"name\":\"magazyn.retrievershop.pl\",\"content\":\"${VPS_TUNNEL_CNAME}\",\"proxied\":true,\"ttl\":1}" \
        2>/dev/null)
    local record_id
    record_id=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result']['id'])" 2>/dev/null)
    if [ -n "$record_id" ]; then
        echo "$record_id" > "$CF_RECORD_FILE"
        log_ok "CF CNAME dodany: magazyn.retrievershop.pl -> VPS tunnel (ID: $record_id)"
        return 0
    else
        log_err "CF CNAME nie dodany: $result"
        return 1
    fi
}

cf_remove_magazyn_cname() {
    local record_id
    record_id=$(cat "$CF_RECORD_FILE" 2>/dev/null)
    if [ -z "$record_id" ]; then
        # Fallback: znajdz rekord przez API
        record_id=$(curl -sf \
            "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?name=magazyn.retrievershop.pl&type=CNAME" \
            -H "Authorization: Bearer ${CF_TOKEN}" 2>/dev/null | \
            python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d.get('result',[]):
    if '59d6c42e' in r.get('content',''):
        print(r['id']); break
" 2>/dev/null)
    fi
    if [ -n "$record_id" ]; then
        curl -sf -X DELETE \
            "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${record_id}" \
            -H "Authorization: Bearer ${CF_TOKEN}" > /dev/null 2>&1
        rm -f "$CF_RECORD_FILE"
        log_ok "CF CNAME usuniety - wildcard przejal (-> minipc)"
    else
        log_warn "CF CNAME: nie znaleziono rekordu do usuniecia"
    fi
}

cloudflared_add_magazyn() {
    local tmp="/tmp/cloudflared_failover_new.yml"
    python3 - "$tmp" << 'PYEOF'
import yaml, sys
cfg_file = '/etc/cloudflared/config.yml'
tmp_file = sys.argv[1]
with open(cfg_file) as f:
    cfg = yaml.safe_load(f) or {}
ingress = cfg.get('ingress', [])
ingress = [r for r in ingress if r.get('hostname') != 'magazyn.retrievershop.pl']
ingress.insert(0, {'hostname': 'magazyn.retrievershop.pl', 'service': 'http://localhost:8000'})
cfg['ingress'] = ingress
with open(tmp_file, 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print('cloudflared: dodano route magazyn')
PYEOF
    if [ $? -eq 0 ] && [ -s "$tmp" ]; then
        sudo cp "$tmp" /etc/cloudflared/config.yml
        rm -f "$tmp"
        sudo systemctl restart cloudflared
        log_ok "cloudflared zrestartowany z route magazyn"
    else
        rm -f "$tmp"
        log_err "cloudflared: blad modyfikacji config - nie restartowano"
        return 1
    fi
}

cloudflared_remove_magazyn() {
    local tmp="/tmp/cloudflared_failover_new.yml"
    python3 - "$tmp" << 'PYEOF'
import yaml, sys
cfg_file = '/etc/cloudflared/config.yml'
tmp_file = sys.argv[1]
with open(cfg_file) as f:
    cfg = yaml.safe_load(f) or {}
ingress = [r for r in cfg.get('ingress', []) if r.get('hostname') != 'magazyn.retrievershop.pl']
cfg['ingress'] = ingress
with open(tmp_file, 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print('cloudflared: usunieto route magazyn')
PYEOF
    if [ $? -eq 0 ] && [ -s "$tmp" ]; then
        sudo cp "$tmp" /etc/cloudflared/config.yml
        rm -f "$tmp"
        sudo systemctl restart cloudflared
        log_ok "cloudflared zrestartowany bez route magazyn"
    else
        rm -f "$tmp"
        log_err "cloudflared: blad modyfikacji config - nie restartowano"
        return 1
    fi
}

save_db_snapshot() {
    # Zapisz snapshot row counts z Mikrus DB przez psycopg2 w kontenerze
    local snap
    snap=$(docker exec magazyn-failover python3 -c "
import psycopg2, json, os
try:
    conn = psycopg2.connect(os.environ.get('DATABASE_URL', '${MIKRUS_DSN}'))
    cur = conn.cursor()
    tables = ['purchase_batches', 'sales', 'allegro_offers']
    result = {}
    for t in tables:
        try:
            cur.execute('SELECT count(*) FROM ' + t)
            result[t] = cur.fetchone()[0]
        except Exception:
            result[t] = -1
    cur.execute(\"SELECT value FROM app_settings WHERE key='ALLEGRO_ACCESS_TOKEN'\")
    row = cur.fetchone()
    result['allegro_token'] = (row[0] or '')[:20] if row else ''
    conn.close()
    print(json.dumps(result))
except Exception as e:
    import sys; print(f'ERR:{e}', file=sys.stderr)
" 2>/dev/null)
    if [ -n "$snap" ] && [[ "$snap" != ERR* ]]; then
        echo "$snap" > "$SNAPSHOT_FILE"
        date +%s > "$ACTIVATE_TIME_FILE"
        log "Snapshot DB: $snap"
    else
        log_warn "Nie udalo sie zapisac snapshotu DB"
        date +%s > "$ACTIVATE_TIME_FILE"
    fi
}

check_db_changes_and_flag() {
    # Porownaj aktualny stan Mikrus DB ze snapshotem sprzed failoveru
    # Jezeli zmiany -> ustaw flage failover_sync_needed w Mikrus DB
    local elapsed=0
    if [ -f "$ACTIVATE_TIME_FILE" ]; then
        elapsed=$(( $(date +%s) - $(<"$ACTIVATE_TIME_FILE") ))
    fi

    local sync_reason=""

    if [ -f "$SNAPSHOT_FILE" ]; then
        local old_snap new_snap diffs
        old_snap="$(<"$SNAPSHOT_FILE")"
        new_snap=$(docker exec magazyn-failover python3 -c "
import psycopg2, json, os
try:
    conn = psycopg2.connect(os.environ.get('DATABASE_URL', '${MIKRUS_DSN}'))
    cur = conn.cursor()
    tables = ['purchase_batches', 'sales', 'allegro_offers']
    result = {}
    for t in tables:
        try:
            cur.execute('SELECT count(*) FROM ' + t)
            result[t] = cur.fetchone()[0]
        except Exception:
            result[t] = -1
    cur.execute(\"SELECT value FROM app_settings WHERE key='ALLEGRO_ACCESS_TOKEN'\")
    row = cur.fetchone()
    result['allegro_token'] = (row[0] or '')[:20] if row else ''
    conn.close()
    print(json.dumps(result))
except Exception as e:
    import sys; print(f'ERR:{e}', file=sys.stderr)
" 2>/dev/null)
        if [ -n "$new_snap" ] && [[ "$new_snap" != ERR* ]]; then
            # Bezpieczne porownanie JSON - przekaz przez argumenty zamiast interpolacji
            diffs=$(python3 -c "
import json, sys
old = json.loads(sys.argv[1])
new = json.loads(sys.argv[2])
print('\n'.join(f'{k}: {old[k]} -> {new.get(k)}' for k in old if str(old[k])!=str(new.get(k,old[k]))))
" "$old_snap" "$new_snap" 2>/dev/null)
            [ -n "$diffs" ] && sync_reason="Zmiany w DB: $(echo "$diffs" | tr '\n' '|')"
        fi
    fi

    # Fallback: failover trwal >5min -> token Allegro mogl sie odswiezyc
    if [ -z "$sync_reason" ] && [ "$elapsed" -gt 300 ]; then
        sync_reason="Failover trwal ${elapsed}s >5min"
    fi

    rm -f "$SNAPSHOT_FILE" "$ACTIVATE_TIME_FILE"

    if [ -n "$sync_reason" ]; then
        log "Reverse sync potrzebny: $sync_reason"
        local flag_result
        flag_result=$(docker exec magazyn-failover python3 -c "
import psycopg2, os
try:
    conn = psycopg2.connect(os.environ.get('DATABASE_URL', '${MIKRUS_DSN}'))
    cur = conn.cursor()
    cur.execute(\"\"\"INSERT INTO app_settings (key, value, updated_at)
        VALUES ('failover_sync_needed', '1', CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO UPDATE SET value='1', updated_at=CURRENT_TIMESTAMP\"\"\")
    conn.commit(); conn.close()
    print('OK')
except Exception as e:
    print(f'ERR:{e}')
" 2>/dev/null)
        if [ "$flag_result" = "OK" ]; then
            log_ok "Flaga failover_sync_needed=1 w Mikrus DB - minipc wykona sync"
            echo "sync_needed"
        else
            log_err "Blad ustawiania flagi: $flag_result"
        fi
    else
        log "Brak zmian podczas failoveru (${elapsed}s) - sync niepotrzebny"
    fi
}

activate_failover() {
    log "=== FAILOVER ACTIVATE ==="

    # 1. Start magazyn container
    log "Startuje magazyn-failover container..."
    if docker ps -a --format '{{.Names}}' | grep -q "^magazyn-failover$"; then
        docker start magazyn-failover
    else
        docker run -d \
            --name magazyn-failover \
            --env-file "$FAILOVER_DIR/magazyn.env" \
            -v "$FAILOVER_DIR/magazyn.env:/app/.env:ro" \
            -v "$FAILOVER_DIR/env.example:/app/.env.example:ro" \
            -v "$FAILOVER_DIR/gunicorn_vps.conf.py:/app/magazyn/gunicorn.conf.py:ro" \
            -v "$FAILOVER_DIR/data:/app/data" \
            -v "$FAILOVER_DIR/agent.log:/app/agent.log" \
            -p 8000:8000 \
            --restart=no \
            retrievershop-suite-magazyn_app
    fi

    log "Czekam 15s na start aplikacji..."
    sleep 15

    # Sprawdz czy wystartowal
    if ! curl -sf --max-time 10 http://localhost:8000/healthz > /dev/null 2>&1; then
        log_warn "Aplikacja nie odpowiada na healthz - kontynuuje mimo to"
    else
        log_ok "Aplikacja odpowiada na localhost:8000"
        # Snapshot DB state (do wykrycia zmian przy recovery)
        save_db_snapshot
    fi

    # 2. Dodaj route do cloudflared VPS
    cloudflared_add_magazyn

    # 3. Cloudflare API: dodaj CNAME (override wildcard -> VPS)
    cf_add_magazyn_cname

    set_state "active"
    log_ok "FAILOVER AKTYWNY - magazyn.retrievershop.pl -> VPS"

    # 4. Powiadomienie (WAHA moze byc niedostepna gdy minipc dead -> Messenger fallback)
    notify "FAILOVER aktywny!
minipc niedostepny od ~${REQUIRED_FAILS} min
magazyn.retrievershop.pl -> VPS
Dane z ostatniego nocnego backupu
$(date '+%Y-%m-%d %H:%M')"
}

deactivate_failover() {
    log "=== FAILOVER DEACTIVATE - minipc wrocil ==="

    # 0. Sprawdz czy byly zmiany podczas failoveru (przed zatrzymaniem kontenera)
    local sync_flag
    sync_flag=$(check_db_changes_and_flag)

    # 1. Usun CNAME z Cloudflare (wildcard przejmuje -> minipc)
    cf_remove_magazyn_cname
    log "Czekam 10s na propagacje DNS..."
    sleep 10

    # 2. Usun route z cloudflared VPS
    cloudflared_remove_magazyn

    # 3. Stop magazyn-failover
    docker stop magazyn-failover 2>/dev/null && log_ok "magazyn-failover zatrzymany"

    set_state "normal"
    set_fail_count 0
    log_ok "FAILOVER DEAKTYWOWANY - minipc primary"

    # 4. Powiadomienie (WAHA dostepna bo minipc zyje)
    local msg
    if [ "$sync_flag" = "sync_needed" ]; then
        msg="RECOVERY: minipc wrocil!
magazyn.retrievershop.pl -> minipc (normalny tryb)
Wykryto zmiany podczas failoveru
Minipc wykona reverse sync: Mikrus DB -> local postgres
Sprawdz logi: ~/failover-sync.log
$(date '+%Y-%m-%d %H:%M')"
    else
        msg="RECOVERY: minipc wrocil!
magazyn.retrievershop.pl -> minipc (normalny tryb)
Brak istotnych zmian - sync niepotrzebny
$(date '+%Y-%m-%d %H:%M')"
    fi
    notify "$msg"
}

# --- Maintenance window: minipc backup/rebuild 03:00-03:45 ---
is_maintenance_window() {
    local hour min
    hour=$(date +%H)
    min=$(date +%M)
    [ "$hour" = "03" ] && [ "$min" -lt 45 ]
}

# -- MAIN ---
mkdir -p "$FAILOVER_DIR"
STATE=$(get_state)
FAILS=$(get_fail_count)

if check_minipc; then
    set_fail_count 0
    if [ "$STATE" = "active" ]; then
        deactivate_failover
    fi
    # Stan normalny - nic nie rob (nie loguj zeby nie smiecic)
else
    FAILS=$(( FAILS + 1 ))
    set_fail_count "$FAILS"
    CHECK_URL="$MINIPC_CHECK_URL"; [ "$STATE" = "active" ] && CHECK_URL="$MINIPC_RECOVERY_URL"
    log "minipc check FAIL ($FAILS/$REQUIRED_FAILS) - URL: $CHECK_URL"

    if [ "$FAILS" -ge "$REQUIRED_FAILS" ] && [ "$STATE" = "normal" ]; then
        if is_maintenance_window; then
            log_warn "Maintenance window (03:00-03:45) - pomijam aktywacje failoveru (minipc backup/rebuild)"
        else
            activate_failover
        fi
    fi
fi
