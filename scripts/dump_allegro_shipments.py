#!/usr/bin/env python3
import json
from magazyn.allegro_api.fulfillment import get_shipment_tracking_numbers
from magazyn.factory import create_app

CHECKOUTS = [
    ("Maria", "b94d1a60-69ae-11f1-b822-3b889f6dec5e", "A004TIBRF9"),
    ("Rybarczyk", "0607cce1-6821-11f1-a3b4-27708eea4f6f", "A004RIQ9Z1"),
]

app = create_app()
with app.app_context():
    for name, cid, keep in CHECKOUTS:
        ships = get_shipment_tracking_numbers(cid)
        print(f"\n=== {name} keep={keep} ===")
        print(json.dumps(ships, indent=2, ensure_ascii=False))
