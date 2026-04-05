#!/usr/bin/env bash
# VPS - Nocny build obrazu Docker z git repo
# Cron: 30 1 * * * /home/suchokrates1/failover/vps-nightly-build.sh >> /home/suchokrates1/failover/build.log 2>&1
#
# Logika:
#   1. git pull w /home/suchokrates1/retrievershop-suite
#   2. docker build z nowym kodem
#   3. Usun stary kontener magazyn-failover (wymusi uzycie nowego image przy nastepnym failoverze)
#   4. Prune starych obrazow
#   5. Powiadomienie o wyniku (Messenger)

set -uo pipefail

REPO_DIR="/home/suchokrates1/retrievershop-suite"
IMAGE_NAME="retrievershop-suite-magazyn_app"
FAILOVER_DIR="/home/suchokrates1/failover"
LOG_PREFIX="[vps-build]"

MESSENGER_TOKEN="EAAX4iohJD3cBO02M8vVI34usmEVRKvgoxsKUqJzEkKr9tvTiRLDxyyhpSsSf2NbHpYKaEuIHCZACz7VSxtZAgp3bfSU8dZCYUqs4mdnjvh5ZBN4igOMnuAiWzBj2tAdn5L34IOwgpTSB8cTZBzqFfjEOfD0kLDyC0ZBeneLQB6TB4ZCRJ919HfEDlknoOcSbYmv"
MESSENGER_RECIPIENT="26562269243364091"
MESSENGER_API="https://graph.facebook.com/v22.0/me/messages"

log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${LOG_PREFIX} $*"; }
log_ok()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${LOG_PREFIX} OK: $*"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${LOG_PREFIX} ERROR: $*"; }

send_messenger() {
    local msg="$1"
    curl -sf --max-time 10 \
        -X POST "$MESSENGER_API" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${MESSENGER_TOKEN}" \
        -d "{\"recipient\":{\"id\":\"${MESSENGER_RECIPIENT}\"},\"messaging_type\":\"UPDATE\",\"message\":{\"text\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$msg")}}" \
        > /dev/null 2>&1
}

log "=== Nocny build VPS start ==="

# Nie buduj jezeli failover jest aktywny
STATE=$(cat "$FAILOVER_DIR/state" 2>/dev/null || echo "normal")
if [ "$STATE" = "active" ]; then
    log "Failover aktywny - pomijam build (kontener jest w uzyciu)"
    exit 0
fi

# 1. Git pull
log "git pull..."
cd "$REPO_DIR" || { log_err "Brak katalogu $REPO_DIR"; exit 1; }

OLD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
if ! git pull --ff-only origin main 2>&1; then
    log_err "git pull nie powiodl sie - probujesz reset"
    git fetch origin main
    git reset --hard origin/main
fi
NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    log "Brak zmian w repo ($OLD_COMMIT) - buduje mimo to (deps mogly sie zmienic)"
fi

log "Commit: $OLD_COMMIT -> $NEW_COMMIT"

# 2. Docker build
log "Docker build..."
BUILD_START=$(date +%s)

if docker build -t "$IMAGE_NAME" -f magazyn/Dockerfile . 2>&1 | tail -5; then
    BUILD_END=$(date +%s)
    BUILD_TIME=$(( BUILD_END - BUILD_START ))
    IMAGE_SIZE=$(docker images "$IMAGE_NAME" --format '{{.Size}}' | head -1)
    log_ok "Build ukonczony w ${BUILD_TIME}s (image: $IMAGE_SIZE)"
else
    log_err "Docker build nie powiodl sie!"
    send_messenger "VPS build BLAD!
Docker build nie powiodl sie
Commit: $NEW_COMMIT
$(date '+%Y-%m-%d %H:%M')"
    exit 1
fi

# 3. Usun stary kontener (wymusi uzycie nowego image przy nastepnym failoverze)
if docker ps -a --format '{{.Names}}' | grep -q "^magazyn-failover$"; then
    # Tylko jezeli nie jest uruchomiony (failover nieaktywny - sprawdzilismy wyzej)
    docker rm -f magazyn-failover 2>/dev/null
    log_ok "Stary kontener magazyn-failover usuniety"
fi

# 4. Prune starych dangling images
PRUNED=$(docker image prune -f 2>/dev/null | grep "reclaimed" || echo "brak")
log "Prune: $PRUNED"

# 5. Sprawdz dysk
DISK_FREE=$(df -h / | awk 'NR==2{print $4}')
log "Wolne miejsce: $DISK_FREE"

log "=== Nocny build VPS koniec ($OLD_COMMIT -> $NEW_COMMIT, ${BUILD_TIME}s) ==="
