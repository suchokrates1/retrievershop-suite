#!/bin/bash
# Wdróż skrypty failover na minipc (~/backup/ + symlinki).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${1:-minipc}"
TARGET="/home/suchokrates1/backup"

FILES=(
    db_freshness.sh
    failover-sync-check.sh
    mikrus-db-sync.sh
    mikrus-db-verify.sh
)

for f in "${FILES[@]}"; do
    scp "${REPO_DIR}/scripts/failover/${f}" "${REMOTE}:${TARGET}/${f}"
    ssh "$REMOTE" "chmod +x ${TARGET}/${f} && sed -i 's/\r$//' ${TARGET}/${f}"
done

echo "Deployed to ${REMOTE}:${TARGET}"
