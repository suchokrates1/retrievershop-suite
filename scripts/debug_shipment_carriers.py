#!/usr/bin/env python3
from magazyn.allegro_api.shipment_management import get_shipment_details
from magazyn.factory import create_app

SAMPLES = [
    ("dup InPost", "51db67fd-8d9f-4765-8428-e024a80fb8e5"),
    ("orig InPost", "deb173f2-154c-45c1-8d2c-4ef0aeb1b555"),
    ("dup DHL", "dd8ffd4b-8fca-4270-9a6a-839a185ad5dd"),
    ("orig DHL", "ca13f3d7-8de3-46f8-984f-f060dab978c2"),
    ("dup Allegro", "8ad7c0dc-0951-447e-bfa5-712f36773c14"),
    ("keep Maria", "6551805c-e442-4859-9305-8a3ce5e94698"),
]

app = create_app()
with app.app_context():
    for label, sid in SAMPLES:
        d = get_shipment_details(sid)
        print(label, sid[:8], "carrier=", d.get("carrier"), "status=", d.get("status"), "wb=", (d.get("waybill") or {}).get("waybill"))
