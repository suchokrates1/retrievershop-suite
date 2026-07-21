#!/bin/bash
set -euo pipefail
hostname

# Read webhook secret from magazyn settings (used as Bearer for newsletter API)
SECRET=$(docker exec retrievershop-magazyn python - <<'PY'
from magazyn.settings_store import settings_store
print(settings_store.get("NEWSLETTER_MAIL_SECRET") or settings_store.get("WOO_WEBHOOK_SECRET") or "")
PY
)
if [ -z "$SECRET" ]; then
  echo "NO_SECRET — generating NEWSLETTER_MAIL_SECRET"
  SECRET=$(python3 - <<'PY'
import secrets; print(secrets.token_urlsafe(32))
PY
)
  docker exec retrievershop-magazyn python - <<PY
from magazyn.settings_store import settings_store
settings_store.set("NEWSLETTER_MAIL_SECRET", """$SECRET""")
print("saved NEWSLETTER_MAIL_SECRET")
PY
fi
echo "secret_len=${#SECRET} suffix=${SECRET: -4}"

# Smoke: unauthorized
code=$(curl -s -o /tmp/nl_unauth.json -w "%{http_code}" -X POST https://magazyn.retrievershop.pl/api/shop-mail/newsletter-welcome -H 'Content-Type: application/json' -d '{"email":"x@y.z","coupon_code":"X"}' || true)
echo "unauth_http=$code"

# Authorized dry send to kontakt
RESP=$(curl -s -w "\nHTTP:%{http_code}" -X POST https://magazyn.retrievershop.pl/api/shop-mail/newsletter-welcome \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $SECRET" \
  -d "{\"email\":\"kontakt@retrievershop.pl\",\"first_name\":\"Dawid\",\"coupon_code\":\"RS10-TESTMAIL\",\"discount_percent\":10,\"valid_days\":30,\"shop_url\":\"https://retrievershop.pl/produkty/\"}")
echo "$RESP"

# Export secret for WP setup via stdout marker
echo "SECRET_FOR_WP=$SECRET"
