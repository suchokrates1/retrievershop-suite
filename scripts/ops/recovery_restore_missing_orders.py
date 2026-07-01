#!/usr/bin/env python3
"""Jednorazowy skrypt naprawczy po wyczyszczeniu bazy produkcyjnej (2026-07-01).

Odtwarza 3 zamowienia Allegro, ktore powstaly PO ostatnim dostepnym backupie
(2026-07-01 03:00) a PRZED wyczyszczeniem bazy. Dane o tym co faktycznie sie
wydarzylo (faktury, przesylki, statusy, konsumpcja magazynu) pochodza z
agent.log - NIE generujemy nowych faktur ani etykiet, tylko odtwarzamy w
bazie stan zgodny z tym co juz naprawde zaszlo.

Uzycie:
    python scripts/ops/recovery_restore_missing_orders.py --dry-run
    python scripts/ops/recovery_restore_missing_orders.py --commit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.factory import create_app
from magazyn.allegro_api.orders import fetch_allegro_order_detail, parse_allegro_order_to_data
from magazyn.db import get_session
from magazyn.models.orders import Order
from magazyn.services.order_sync import sync_order_from_data
from magazyn.services.order_status import add_order_status
from magazyn.services.print_agent_storage import PrintAgentStorage
from magazyn.domain.inventory import consume_order_stock
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recovery")

# Dane potwierdzone z agent.log (przed wyczyszczeniem bazy 2026-07-01 wieczorem)
RECOVERY_PLAN = [
    {
        "checkout_form_id": "b80856b0-7525-11f1-8dd6-bd0f39ea4cf2",
        "courier_code": "ALLEGRO",
        "delivery_package_nr": "A004YN40V2",
        "wfirma_invoice_id": 637768885,
        "wfirma_invoice_number": "FBV 409/2026",
        "status_history": ["wydrukowano", "wyslano"],
    },
    {
        "checkout_form_id": "18752cb1-7528-11f1-90e3-bba67ee27a03",
        "courier_code": "INPOST",
        "delivery_package_nr": "620999681866620431462738",
        "wfirma_invoice_id": 637811893,
        "wfirma_invoice_number": "FBV 410/2026",
        "status_history": ["wydrukowano", "wyslano"],
    },
    {
        "checkout_form_id": "e701a040-7546-11f1-a335-7921199afe3e",
        "courier_code": "INPOST",
        "delivery_package_nr": "620999681880680673083534",
        "wfirma_invoice_id": 638295925,
        "wfirma_invoice_number": "FBV 411/2026",
        "status_history": ["wydrukowano"],
    },
]

_print_storage = PrintAgentStorage(
    logger=logger,
    now=lambda: datetime.now(timezone.utc),
    handle_readonly_error=lambda _op, _exc: False,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        for plan in RECOVERY_PLAN:
            order_id = f"allegro_{plan['checkout_form_id']}"
            logger.info("=== Przetwarzam %s ===", order_id)

            with get_session() as db:
                existing = db.query(Order).filter(Order.order_id == order_id).first()
                if existing:
                    logger.warning("Zamowienie %s JUZ ISTNIEJE w bazie - pomijam!", order_id)
                    continue

            detail = fetch_allegro_order_detail(plan["checkout_form_id"])
            order_data = parse_allegro_order_to_data(detail)

            logger.info(
                "  Klient=%s email=%s kwota_produkty=%s",
                order_data.get("customer"),
                order_data.get("email"),
                sum(
                    float(p.get("price_brutto", 0)) * int(p.get("quantity", 1))
                    for p in order_data.get("products", [])
                ),
            )
            for p in order_data.get("products", []):
                logger.info("    - %s x%s ean=%s", p.get("name"), p.get("quantity"), p.get("ean"))

            if args.dry_run:
                logger.info(
                    "  [DRY-RUN] Utworzylbym zamowienie, ustawil courier=%s tracking=%s faktura=%s (%s), "
                    "historia statusow=%s, odjalbym stan magazynu, wpisal do printed_orders.",
                    plan["courier_code"],
                    plan["delivery_package_nr"],
                    plan["wfirma_invoice_number"],
                    plan["wfirma_invoice_id"],
                    plan["status_history"],
                )
                continue

            with get_session() as db:
                order = sync_order_from_data(db, order_data)
                order.courier_code = plan["courier_code"]
                order.delivery_package_nr = plan["delivery_package_nr"]
                order.wfirma_invoice_id = plan["wfirma_invoice_id"]
                order.wfirma_invoice_number = plan["wfirma_invoice_number"]

                for status in plan["status_history"]:
                    add_order_status(
                        db,
                        order_id,
                        status,
                        notes="Recovery po wyczyszczeniu bazy 2026-07-01: odtworzone z agent.log",
                    )

                _print_storage.upsert_printed_order_record(
                    order_id,
                    {
                        "courier_code": plan["courier_code"],
                        "delivery_package_nr": plan["delivery_package_nr"],
                        "recovery": True,
                    },
                    db_session=db,
                )
                db.commit()
                logger.info("  Zapisano zamowienie %s w bazie.", order_id)

            consume_order_stock(order_data.get("products", []))
            logger.info("  Odjeto stan magazynowy dla %s.", order_id)

    logger.info("Gotowe.")


if __name__ == "__main__":
    main()
