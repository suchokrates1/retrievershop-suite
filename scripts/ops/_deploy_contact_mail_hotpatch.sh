#!/bin/bash
# Hot-patch shop-mail/contact into running magazyn (no rebuild).
set -euo pipefail
hostname
test "$(hostname)" = "minipc"

SRC_DIR="${1:?usage: $0 /path/to/local-files-dir}"
docker cp "$SRC_DIR/mail_api.py" retrievershop-magazyn:/app/magazyn/blueprints/shop/mail_api.py
docker cp "$SRC_DIR/email_service.py" retrievershop-magazyn:/app/magazyn/services/email_service.py
docker restart retrievershop-magazyn
echo "restarted, waiting health..."
for i in $(seq 1 30); do
  if docker exec retrievershop-magazyn curl -sf http://localhost:8000/healthz >/dev/null; then
    echo "healthy"
    break
  fi
  sleep 2
done
docker exec retrievershop-magazyn curl -sf http://localhost:8000/healthz || { echo "NOT healthy"; exit 1; }
