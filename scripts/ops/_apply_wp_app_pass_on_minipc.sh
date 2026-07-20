#!/bin/bash
set -eu
CREDS=$(ssh -o BatchMode=yes rpi 'cat /tmp/wp_app_pass.txt')
USER=$(printf '%s\n' "$CREDS" | sed -n '1p' | tr -d '\r')
PASS=$(printf '%s\n' "$CREDS" | sed -n '2p' | tr -d '\r')

docker exec \
  -e PYTHONPATH=/app \
  -e WP_APP_USER="$USER" \
  -e WP_APP_PASSWORD="$PASS" \
  -w /app \
  retrievershop-magazyn python -c '
import os
from magazyn.settings_store import settings_store
settings_store.update({
    "WP_APP_USER": os.environ["WP_APP_USER"],
    "WP_APP_PASSWORD": os.environ["WP_APP_PASSWORD"],
})
print("wp_app_ok", os.environ["WP_APP_USER"], "pass_len", len(os.environ["WP_APP_PASSWORD"]))
'
