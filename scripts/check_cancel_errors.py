#!/usr/bin/env python3
from magazyn.allegro_api.shipment_management import get_cancel_command_status
from magazyn.factory import create_app

IDS = [
    ("InPost dup", "48718d8a-f473-467e-bbdf-d884539832dd"),
    ("InPost dup2", "bdb4bcb3-14ea-4b18-954f-17d9844148e0"),
    ("Allegro dup", "e0384d8b-cc86-4dc3-b77c-1097557e9d5c"),
]

app = create_app()
with app.app_context():
    for label, cid in IDS:
        print(label, get_cancel_command_status(cid))
