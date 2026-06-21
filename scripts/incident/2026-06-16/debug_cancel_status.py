#!/usr/bin/env python3
from magazyn.allegro_api.shipment_management import get_cancel_command_status, get_shipment_details
from magazyn.factory import create_app

COMMANDS = [
    ("A004TIAF94", "8ad7c0dc-0951-447e-bfa5-712f36773c14", "e0384d8b-cc86-4dc3-b77c-1097557e9d5c"),
    ("AD02LQ90M4", "dd8ffd4b-8fca-4270-9a6a-839a185ad5dd", "9bc1fca4-b192-434b-a4be-749202d29d04"),
]

app = create_app()
with app.app_context():
    for wb, sid, cid in COMMANDS:
        print("===", wb, sid)
        try:
            d = get_shipment_details(sid)
            print("details:", {k: d.get(k) for k in ("status", "carrier", "createdAt")})
            print("waybill:", d.get("waybill"))
        except Exception as e:
            print("details error:", e)
        try:
            s = get_cancel_command_status(cid)
            print("cancel status:", s)
        except Exception as e:
            print("cancel error:", e)
