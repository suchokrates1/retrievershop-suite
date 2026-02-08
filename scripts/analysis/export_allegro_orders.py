"""
Eksport zamowien z Allegro REST API.

Uruchamiac wewnatrz kontenera:
  flask shell < scripts/analysis/export_allegro_orders.py

Lub przez docker exec:
  docker exec -i retrievershop-suite-magazyn_app-1 flask shell < scripts/analysis/export_allegro_orders.py
"""
import json
import sys

from magazyn.allegro_api.orders import fetch_all_allegro_orders

print("Pobieranie zamowien z Allegro API...", file=sys.stderr)

try:
    orders = fetch_all_allegro_orders(
        progress_callback=lambda fetched, total: print(
            f"  Pobrano {fetched}/{total}...", file=sys.stderr
        )
    )
    print(f"Pobrano {len(orders)} zamowien z Allegro API", file=sys.stderr)
    print(json.dumps(orders, ensure_ascii=False, indent=2))
except Exception as exc:
    print(f"BLAD: {exc}", file=sys.stderr)
    sys.exit(1)
