#!/bin/bash
# Odswiez token Allegro w bazie magazyn PRZED pg_dump.
# Wywoluj z backup.sh (minipc), deploy CI lub recznie przed backupem.
#
# Zmienne srodowiskowe (opcjonalne):
#   MAGAZYN_CONTAINER  domyslnie retrievershop-magazyn
#   REFRESH_SCRIPT     sciezka w kontenerze do refresh_allegro_token.py
set -uo pipefail

MAGAZYN_CONTAINER="${MAGAZYN_CONTAINER:-retrievershop-magazyn}"
REFRESH_SCRIPT="${REFRESH_SCRIPT:-/app/scripts/ops/refresh_allegro_token.py}"

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$MAGAZYN_CONTAINER"; then
    echo "WARN: kontener $MAGAZYN_CONTAINER nie dziala - pomijam odswiezenie tokenu Allegro" >&2
    exit 0
fi

if ! docker exec "$MAGAZYN_CONTAINER" test -f "$REFRESH_SCRIPT" 2>/dev/null; then
    echo "WARN: brak $REFRESH_SCRIPT w obrazie - pomijam odswiezenie (wymaga deploy)" >&2
    exit 0
fi

docker exec "$MAGAZYN_CONTAINER" python3 "$REFRESH_SCRIPT"
