#!/bin/bash
# Wdróż skrypty failover na minipc (~/backup/ + symlinki).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${1:-minipc}"
TARGET="/home/suchokrates1/backup"

FAILOVER_FILES=(
    db_freshness.sh
    failover-sync-check.sh
    mikrus-db-sync.sh
    mikrus-db-verify.sh
)

for f in "${FAILOVER_FILES[@]}"; do
    scp "${REPO_DIR}/scripts/failover/${f}" "${REMOTE}:${TARGET}/${f}"
    ssh "$REMOTE" "chmod +x ${TARGET}/${f} && sed -i 's/\r$//' ${TARGET}/${f}"
done

scp "${REPO_DIR}/scripts/ops/refresh_allegro_token_before_backup.sh" \
    "${REMOTE}:${TARGET}/refresh_allegro_token_before_backup.sh"
ssh "$REMOTE" "chmod +x ${TARGET}/refresh_allegro_token_before_backup.sh && sed -i 's/\r$//' ${TARGET}/refresh_allegro_token_before_backup.sh"

echo "Deployed to ${REMOTE}:${TARGET}"
