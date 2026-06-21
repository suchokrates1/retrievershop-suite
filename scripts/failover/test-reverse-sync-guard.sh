#!/bin/bash
# Test guard: flag=1 przy identycznych bazach → SKIP bez nadpisania
set -euo pipefail
source /home/suchokrates1/backup/failover-sync.secrets.env
export MIKRUS_PASS WAHA_KEY

docker exec -e PGPASSWORD="$MIKRUS_PASS" retrievershop-postgres \
  psql -h psql01.mikr.us -U robert136 -d db_robert136 \
  -c "UPDATE app_settings SET value='1' WHERE key='failover_sync_needed';"

bash /home/suchokrates1/backup/failover-sync-check.sh

FLAG=$(docker exec -e PGPASSWORD="$MIKRUS_PASS" retrievershop-postgres \
  psql -h psql01.mikr.us -U robert136 -d db_robert136 \
  -tAc "SELECT value FROM app_settings WHERE key='failover_sync_needed';")

echo "failover_sync_needed=$FLAG"
