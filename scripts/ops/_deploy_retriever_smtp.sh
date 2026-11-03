#!/usr/bin/env bash
# Deploy Retriever SMTP MU-plugin on WP (dell) using SMTP from magazyn (minipc).
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"
TEST_TO="${1:-dawsuchodolski@gmail.com}"

echo "== hostname =="
hostname

echo "== fetch SMTP from magazyn =="
# Run on minipc via ssh from wherever; this script is intended to run from Windows via:
#   scp + ssh dell ... OR orchestrated externally.
# Prefer env vars already injected by caller.
: "${SMTP_SERVER:?}"
: "${SMTP_PORT:?}"
: "${SMTP_USERNAME:?}"
: "${SMTP_PASSWORD:?}"
: "${EMAIL_FROM_NAME:=Retriever Shop}"

docker cp "$BASE/_mu_retriever_smtp.php" retrievershop-wp:/var/www/html/wp-content/mu-plugins/retriever-smtp.php
docker exec retrievershop-wp chown www-data:www-data /var/www/html/wp-content/mu-plugins/retriever-smtp.php

docker cp "$BASE/_configure_retriever_smtp.php" retrievershop-wp:/tmp/_configure_retriever_smtp.php
docker exec \
  -e "SMTP_SERVER=${SMTP_SERVER}" \
  -e "SMTP_PORT=${SMTP_PORT}" \
  -e "SMTP_USERNAME=${SMTP_USERNAME}" \
  -e "SMTP_PASSWORD=${SMTP_PASSWORD}" \
  -e "EMAIL_FROM_NAME=${EMAIL_FROM_NAME}" \
  -e "TEST_TO=${TEST_TO}" \
  retrievershop-wp php /tmp/_configure_retriever_smtp.php

echo "DONE"
