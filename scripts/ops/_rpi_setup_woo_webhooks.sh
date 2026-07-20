#!/bin/bash
set -euo pipefail
python3 - <<'PY'
import secrets
from pathlib import Path
Path("/tmp/woo_webhook_secret.txt").write_text(secrets.token_hex(24), encoding="utf-8")
print("secret written")
PY
SECRET=$(cat /tmp/woo_webhook_secret.txt)
docker cp /tmp/_fix_woo_webhook_secret.php retrievershop-wp:/tmp/_fix_woo_webhook_secret.php
docker exec -e WOO_WEBHOOK_SECRET="$SECRET" retrievershop-wp \
  php /var/www/html/wp-cli.phar eval-file /tmp/_fix_woo_webhook_secret.php --allow-root
echo "done secret_len=${#SECRET}"
