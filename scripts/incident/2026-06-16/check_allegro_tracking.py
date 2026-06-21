#!/usr/bin/env python3
"""Check Allegro fulfillment tracking for incident orders."""
from magazyn.allegro_api.fulfillment import get_shipment_tracking_numbers
from magazyn.factory import create_app

ORDERS = [
    ("Maria", "b94d1a60-69ae-11f1-b822-3b889f6dec5e"),
    ("Rybarczyk", "0607cce1-6821-11f1-a3b4-27708eea4f6f"),
    ("Szczurek", "0607cce1-6821-11f1-a3b4-27708eea4f6f"),  # fix below
    ("Gębusia/DHL", "d259ffa0-6454-11f1-b09e-572fb364178c"),
    ("Jankowski/DHL", "dfa0e3e0-687d-11f1-a3b1-4316fada8457"),
    ("Pronobis", "bf1de1b0-6641-11f1-b9ca-7f92d3ec60b8"),
]

ORDERS = [
    ("Maria", "b94d1a60-69ae-11f1-b822-3b889f6dec5e"),
    ("Rybarczyk", "0607cce1-6821-11f1-a3b4-27708eea4f6f"),
    ("Gębusia", "d259ffa0-6454-11f1-b09e-572fb364178c"),
    ("Jankowski", "dfa0e3e0-687d-11f1-a3b1-4316fada8457"),
    ("Pronobis/Kędzior", "bf1de1b0-6641-11f1-b9ca-7f92d3ec60b8"),
    ("Leszczyński", "1002a0e0-680c-11f1-9c59-0d1dedc4969b"),
]

app = create_app()
with app.app_context():
    for name, checkout_id in ORDERS:
        try:
            tracks = get_shipment_tracking_numbers(checkout_id)
            nums = [t.get("waybill") or t.get("trackingNumber") for t in (tracks or [])]
            print(f"{name:15} {checkout_id[:8]}... tracking count={len(nums)}: {nums}")
        except Exception as exc:
            print(f"{name:15} ERROR: {exc}")
