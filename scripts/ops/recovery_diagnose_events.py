#!/usr/bin/env python3
"""Diagnostyka odzyskiwania po wyczyszczeniu bazy: pokaz zdarzenia Allegro
od ostatniego zapisanego kursora, bez zadnego zapisu do bazy zamowien.

Uzycie (w kontenerze magazyn_app):
    python scripts/ops/recovery_diagnose_events.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.factory import create_app
from magazyn.allegro_api.events import fetch_order_events
from magazyn.allegro_api.orders import fetch_allegro_order_detail, parse_allegro_order_to_data, get_allegro_internal_status
from magazyn.settings_store import settings_store
from magazyn.db import get_session
from magazyn.models.orders import Order

IMPORT_EVENT_TYPES = {"BOUGHT", "FILLED_IN", "READY_FOR_PROCESSING"}
CANCEL_EVENT_TYPES = {"BUYER_CANCELLED", "AUTO_CANCELLED"}


def main() -> None:
    app = create_app()
    with app.app_context():
        last_event_id = settings_store.get("ALLEGRO_LAST_EVENT_ID")
        print(f"Kursor ALLEGRO_LAST_EVENT_ID w bazie: {last_event_id}")

        result = fetch_order_events(from_event_id=last_event_id, limit=1000)
        events = result.get("events", [])
        print(f"Pobrano {len(events)} zdarzen od kursora.\n")

        seen = set()
        for event in events:
            event_type = event.get("type", "")
            order_info = event.get("order", {})
            checkout_form_id = order_info.get("checkoutForm", {}).get("id")
            occurred_at = event.get("occurredAt", "")
            if not checkout_form_id:
                continue
            if event_type not in IMPORT_EVENT_TYPES and event_type not in CANCEL_EVENT_TYPES:
                continue
            if checkout_form_id in seen:
                continue
            seen.add(checkout_form_id)

            order_id = f"allegro_{checkout_form_id}"
            with get_session() as db:
                exists = db.query(Order).filter(Order.order_id == order_id).first() is not None

            print(f"=== event={event_type} occurred_at={occurred_at} checkout_form_id={checkout_form_id} ===")
            print(f"  Juz w lokalnej bazie: {exists}")

            if event_type in CANCEL_EVENT_TYPES:
                continue

            try:
                detail = fetch_allegro_order_detail(checkout_form_id)
            except Exception as exc:
                print(f"  BLAD pobierania szczegolow: {exc}")
                continue

            order_data = parse_allegro_order_to_data(detail)
            internal_status = get_allegro_internal_status(order_data)
            fulfillment = detail.get("fulfillment", {}) or {}
            summary = detail.get("summary", {}) or {}
            total = summary.get("totalToPay", {}) or {}
            delivery = detail.get("delivery", {}) or {}
            print(f"  Klient: {order_data.get('customer')} ({order_data.get('email')})")
            print(f"  Kwota: {total.get('amount')} {total.get('currency')}")
            print(f"  Platnosc: {order_data.get('payment_method')} cod={order_data.get('payment_method_cod')} payment_done={order_data.get('payment_done')}")
            print(f"  Fulfillment status: {fulfillment.get('status')}")
            print(f"  Internal status wyliczony: {internal_status}")
            print(f"  Delivery.smart: {delivery.get('smart')}, method: {(delivery.get('method') or {}).get('name')}")
            print(f"  Produkty:")
            for p in order_data.get("products", []):
                print(f"    - {p.get('name')} x{p.get('quantity')} ean={p.get('ean')} price_brutto={p.get('price_brutto')}")
            print()


if __name__ == "__main__":
    main()
