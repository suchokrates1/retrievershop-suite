#!/bin/bash
# Wdróż skrypty failover na VPS Mikrus.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${1:-vps}"
TARGET="/home/suchokrates1/failover"

FILES=(
    common.sh
    failover.sh
    vps-nightly-build.sh
)

for f in "${FILES[@]}"; do
    scp "${REPO_DIR}/scripts/failover/${f}" "${REMOTE}:${TARGET}/${f}"
    ssh "$REMOTE" "chmod +x ${TARGET}/${f} && sed -i 's/\r$//' ${TARGET}/${f}"
done

echo "Deployed to ${REMOTE}:${TARGET}"
