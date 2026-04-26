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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_FILE="${FAILOVER_COMMON:-$SCRIPT_DIR/common.sh}"
if [ ! -f "$COMMON_FILE" ] && [ -f "$FAILOVER_DIR/common.sh" ]; then
    COMMON_FILE="$FAILOVER_DIR/common.sh"
fi
if [ ! -f "$COMMON_FILE" ]; then
    echo "FATAL: Brak common.sh" >&2
    exit 1
fi
. "$COMMON_FILE"

# --- Sekrety z pliku ---
SECRETS_FILE="$FAILOVER_DIR/secrets.env"
load_secrets "$SECRETS_FILE"

LOCK_FILE="$FAILOVER_DIR/vps-nightly-build.lock"
exec 201>"$LOCK_FILE"
flock -n 201 || { log "Inny nightly build juz dziala - pomijam"; exit 0; }

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
if [ -n "$(git status --porcelain)" ]; then
    log_err "Repo na VPS ma lokalne zmiany - przerywam build bez resetowania"
    send_messenger "VPS build BLAD!
Repo ma lokalne zmiany, build przerwany bez resetowania
Commit: $OLD_COMMIT
$(date '+%Y-%m-%d %H:%M')"
    exit 1
fi

if ! git fetch origin main 2>&1; then
    log_err "git fetch nie powiodl sie"
    send_messenger "VPS build BLAD!
git fetch nie powiodl sie
Commit: $OLD_COMMIT
$(date '+%Y-%m-%d %H:%M')"
    exit 1
fi

if ! git merge --ff-only origin/main 2>&1; then
    log_err "git merge --ff-only nie powiodl sie - przerywam bez resetowania"
    send_messenger "VPS build BLAD!
Nie mozna wykonac fast-forward merge, build przerwany bez resetowania
Commit: $OLD_COMMIT
$(date '+%Y-%m-%d %H:%M')"
    exit 1
fi
NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    log "Brak zmian w repo ($OLD_COMMIT) - buduje mimo to (deps mogly sie zmienic)"
fi

log "Commit: $OLD_COMMIT -> $NEW_COMMIT"

# 2. Docker build
log "Docker build..."
BUILD_START=$(date +%s)

if docker build --pull -t "$IMAGE_NAME" -f magazyn/Dockerfile . 2>&1 | tail -5; then
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

log "Smoke test obrazu..."
if docker run --rm --entrypoint python "$IMAGE_NAME" -m compileall -q /app/magazyn; then
    log_ok "Smoke test obrazu przeszedl"
else
    log_err "Smoke test obrazu nie powiodl sie"
    send_messenger "VPS build BLAD!
Smoke test obrazu nie powiodl sie
Commit: $NEW_COMMIT
$(date '+%Y-%m-%d %H:%M')"
    exit 1
fi

# 3. Usun stary kontener (wymusi uzycie nowego image przy nastepnym failoverze)
if docker ps --format '{{.Names}}' | grep -q "^magazyn-failover$"; then
    log_warn "magazyn-failover jest uruchomiony - nie usuwam kontenera"
elif docker ps -a --format '{{.Names}}' | grep -q "^magazyn-failover$"; then
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
