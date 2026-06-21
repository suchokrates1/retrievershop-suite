#!/usr/bin/env python3
"""Uzupełnij tracking_numbers w printed_orders o numery przewoźnika z Allegro SM."""
from __future__ import annotations

import argparse
import json

from magazyn.allegro_api.shipment_management import get_shipment_details, get_shipment_label
from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.printing import PrintedOrder
from magazyn.services.label_barcode_extract import (
    extract_dhl_box_barcodes_from_label_pdf,
    needs_dhl_box_label_barcode_extraction,
)
from magazyn.services.print_agent_order_data import apply_package_tracking
from magazyn.services.scanning import parse_last_order_data
from magazyn.services.shipment_waybills import extract_waybills_from_shipment_details


def _collect_waybills(package_ids: list[str], delivery_method: str) -> list[str]:
    waybills: list[str] = []
    for package_id in package_ids:
        details = get_shipment_details(package_id)
        waybills.extend(extract_waybills_from_shipment_details(details))
        if needs_dhl_box_label_barcode_extraction(delivery_method):
            try:
                label_bytes = get_shipment_label([package_id], page_size="A6", cut_line=False)
                waybills.extend(extract_dhl_box_barcodes_from_label_pdf(label_bytes))
            except Exception as exc:
                print(f"  label fetch failed for {package_id}: {exc}")
    return list(dict.fromkeys(waybills))


def backfill(*, dry_run: bool = False) -> int:
    updated = 0
    with get_session() as db:
        for printed_order in db.query(PrintedOrder).all():
            data = parse_last_order_data(printed_order.last_order_data)
            package_ids = [str(value) for value in (data.get("package_ids") or []) if value]
            if not package_ids:
                continue

            delivery_method = str(
                data.get("shipping") or data.get("delivery_method") or ""
            )
            waybills = _collect_waybills(package_ids, delivery_method)
            if not waybills:
                continue

            existing = [str(value) for value in (data.get("tracking_numbers") or [])]
            if existing == waybills:
                continue

            apply_package_tracking(
                data,
                courier_code=data.get("courier_code") or data.get("delivery_package_module") or "",
                package_ids=package_ids,
                tracking_numbers=waybills,
            )
            print(
                f"{printed_order.order_id}: "
                f"{existing} -> {data.get('tracking_numbers')}"
            )
            if not dry_run:
                printed_order.last_order_data = json.dumps(data, ensure_ascii=False)
                updated += 1

        if not dry_run:
            db.commit()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        count = backfill(dry_run=args.dry_run)
    print(f"Updated {count} printed orders")


if __name__ == "__main__":
    main()
