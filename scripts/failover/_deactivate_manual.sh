#!/usr/bin/env bash
set -e

echo "=== Reczna deaktywacja failovera ==="

SECRETS_FILE="/home/suchokrates1/failover/secrets.env"
if [ ! -f "$SECRETS_FILE" ]; then echo "FATAL: Brak $SECRETS_FILE" >&2; exit 1; fi
. "$SECRETS_FILE"

# 1. Stop kontener
docker stop magazyn-failover 2>/dev/null && echo "Kontener zatrzymany" || echo "Kontener juz zatrzymany"

# 2. Usun CNAME z Cloudflare
RECORD_ID=$(cat /home/suchokrates1/failover/cf_record_id 2>/dev/null)
if [ -n "$RECORD_ID" ]; then
    curl -sf -X DELETE \
        "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${RECORD_ID}" \
        -H "Authorization: Bearer ${CF_TOKEN}" > /dev/null 2>&1 \
        && echo "CNAME usuniety (ID: $RECORD_ID)" \
        || echo "WARN: nie mozna usunac CNAME"
    rm -f /home/suchokrates1/failover/cf_record_id
else
    echo "Brak CNAME do usuniecia"
fi

# 3. Usun route z cloudflared VPS
python3 - << 'PYEOF'
import yaml
cfg_file = '/etc/cloudflared/config.yml'
try:
    with open(cfg_file) as f:
        cfg = yaml.safe_load(f) or {}
    ingress = [r for r in cfg.get('ingress', []) if r.get('hostname') != 'magazyn.retrievershop.pl']
    if len(ingress) != len(cfg.get('ingress', [])):
        cfg['ingress'] = ingress
        with open(cfg_file, 'w') as f:
            yaml.dump(cfg, f, default_flow_style=False)
        print("cloudflared: usunieto route magazyn")
    else:
        print("cloudflared: brak route magazyn do usuniecia")
except Exception as e:
    print(f"WARN: {e}")
PYEOF
sudo systemctl restart cloudflared 2>/dev/null && echo "cloudflared zrestartowany" || true

# 4. Reset state
echo "normal" > /home/suchokrates1/failover/state
echo "0" > /home/suchokrates1/failover/fail_count
echo "State: $(cat /home/suchokrates1/failover/state)"
echo "=== Deaktywacja zakonczona ==="
