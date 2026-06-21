#!/usr/bin/env bash
# Wspólne metryki świeżości bazy local vs Mikrus (reverse sync guard + monitoring).

: "${LOCAL_CONTAINER:=retrievershop-postgres}"
: "${LOCAL_USER:=magazyn}"
: "${LOCAL_DB:=magazyn}"
: "${MIKRUS_HOST:=psql01.mikr.us}"
: "${MIKRUS_USER:=robert136}"
: "${MIKRUS_DB:=db_robert136}"

FRESHNESS_SQL="
SELECT json_build_object(
  'offers', (SELECT count(*)::int FROM allegro_offers),
  'sales', (SELECT count(*)::int FROM sales),
  'orders', (SELECT count(*)::int FROM orders),
  'max_sale', COALESCE((SELECT max(sale_date)::text FROM sales), ''),
  'max_order', COALESCE((SELECT max(date_add)::text FROM orders), '')
)::text
"

db_freshness_query() {
    local host="${1:-}"
    local user="${2:-$LOCAL_USER}"
    local db="${3:-$LOCAL_DB}"
    local pass="${4:-}"

    if [ -n "$host" ]; then
        docker exec -e PGPASSWORD="$pass" "$LOCAL_CONTAINER" \
            psql -h "$host" -U "$user" -d "$db" -tAc "$FRESHNESS_SQL" 2>/dev/null \
            | tr -d '[:space:]'
    else
        docker exec "$LOCAL_CONTAINER" \
            psql -U "$user" -d "$db" -tAc "$FRESHNESS_SQL" 2>/dev/null \
            | tr -d '[:space:]'
    fi
}

db_freshness_local_metrics() {
    db_freshness_query "" "$LOCAL_USER" "$LOCAL_DB" ""
}

db_freshness_mikrus_metrics() {
    db_freshness_query "$MIKRUS_HOST" "$MIKRUS_USER" "$MIKRUS_DB" "$MIKRUS_PASS"
}

# Zwraca 0 gdy local jest wyraźnie nowszy — reverse sync powinien być ODRZUCONY.
# Zwraca 1 gdy Mikrus jest nowszy/równy — reverse sync może iść dalej.
db_freshness_local_is_newer() {
    local local_json="$1"
    local mikrus_json="$2"
    python3 - "$local_json" "$mikrus_json" <<'PY'
import json, sys

def load(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}

local = load(sys.argv[1])
mikrus = load(sys.argv[2])

def num(d, key):
    try:
        return int(d.get(key) or 0)
    except (TypeError, ValueError):
        return 0

def text(d, key):
    return str(d.get(key) or "")

lo, mo = num(local, "offers"), num(mikrus, "offers")
ls, ms = num(local, "sales"), num(mikrus, "sales")
lor, mor = num(local, "orders"), num(mikrus, "orders")
lms, mms = text(local, "max_sale"), text(mikrus, "max_sale")
lmo, mmo = text(local, "max_order"), text(mikrus, "max_order")

# Wyraźnie więcej danych biznesowych na minipc → nie nadpisuj.
if lo > mo:
    sys.exit(0)
if ls > ms:
    sys.exit(0)
if lms and mms and lms > mms:
    sys.exit(0)
if lor > mor:
    sys.exit(0)
if lmo and mmo and lmo > mmo:
    sys.exit(0)

# Mikrus ma mniej ofert przy porównywalnej reszcie → local nowszy (typowy incydent).
if lo >= mo and mo > 0 and lo - mo >= 5:
    sys.exit(0)

sys.exit(1)
PY
}

db_freshness_format() {
    python3 - "$1" <<'PY'
import json, sys
try:
    d = json.loads(sys.argv[1] or "{}")
except json.JSONDecodeError:
    print(sys.argv[1] or "(brak)")
    sys.exit(0)
print(
    f"offers={d.get('offers', '?')} sales={d.get('sales', '?')} orders={d.get('orders', '?')} "
    f"max_sale={d.get('max_sale') or '-'} max_order={d.get('max_order') or '-'}"
)
PY
}

db_freshness_metrics_equal() {
    local local_json="$1"
    local mikrus_json="$2"
    [ "$local_json" = "$mikrus_json" ]
}
