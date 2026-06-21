#!/usr/bin/env python3
"""Diagnostyka skanów etykiet — jednorazowy skrypt ops."""
import json
import sys

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.printing import PrintedOrder, ScanLog
from magazyn.services.scanning import barcode_matches_order, parse_last_order_data
from sqlalchemy import desc


def main():
    app = create_app()
    with app.app_context():
        _run()


def _run():
    failed = sys.argv[1:] or [
        "2102413302196",
        "2LPL02495+83545000",
        "JJD000030230864000435460935",
    ]

    with get_session() as db:
        print("=== Ostatnie nieudane skany ===")
        logs = (
            db.query(ScanLog)
            .filter(ScanLog.success.is_(False))
            .order_by(desc(ScanLog.created_at))
            .limit(10)
            .all()
        )
        for log in logs:
            print(
                f"  {log.created_at} | {log.scan_type} | {log.barcode[:60]} | {log.error_message}"
            )

        orders = db.query(PrintedOrder).all()
        print(f"\nTotal printed orders: {len(orders)}")

        for bc in failed:
            print(f"\n=== Barcode: {bc} ===")
            found = False
            for po in orders:
                data = parse_last_order_data(po.last_order_data)
                if barcode_matches_order(data, bc):
                    print(f"MATCH order_id={po.order_id}")
                    print(f"  shipping={data.get('shipping')} courier={data.get('courier_code')}")
                    print(f"  delivery_package_nr={data.get('delivery_package_nr')}")
                    print(f"  tracking_numbers={data.get('tracking_numbers')}")
                    print(f"  package_ids={data.get('package_ids')}")
                    found = True
            if not found:
                print("No match in printed_orders")

        print("\n=== Ostatnie Orlen/DHL w printed_orders ===")
        orlen_dhl = []
        for po in sorted(orders, key=lambda x: x.order_id, reverse=True):
            data = parse_last_order_data(po.last_order_data)
            ship = f"{data.get('shipping', '')} {data.get('courier_code', '')}".upper()
            if "ORLEN" in ship or "DHL" in ship:
                orlen_dhl.append(po)
                print(
                    f"  {po.order_id} | {data.get('shipping')} | "
                    f"nr={data.get('delivery_package_nr')} | "
                    f"track={data.get('tracking_numbers')} | "
                    f"pkg={data.get('package_ids')}"
                )

        # Allegro API: checkout-form shipments + SM details
        try:
            from magazyn.allegro_api.fulfillment import get_shipment_tracking_numbers
            from magazyn.allegro_api.shipment_management import get_shipment_details
        except ImportError as exc:
            print(f"\nAllegro API import failed: {exc}")
            return

        print("\n=== Allegro API — shipments vs SM waybill ===")
        for po in orlen_dhl[:5]:
            checkout_id = po.order_id.replace("allegro_", "", 1)
            print(f"\n  order {po.order_id}")
            try:
                shipments = get_shipment_tracking_numbers(checkout_id)
                print(f"    checkout-form shipments: {shipments}")
            except Exception as exc:
                print(f"    checkout-form error: {exc}")

            data = parse_last_order_data(po.last_order_data)
            for pkg_id in data.get("package_ids") or []:
                try:
                    details = get_shipment_details(pkg_id)
                    pkgs = details.get("packages") or []
                    print(f"    SM {pkg_id}: carrier={details.get('carrier')} packages={pkgs}")
                except Exception as exc:
                    print(f"    SM {pkg_id} error: {exc}")

        print("\n=== Wszystkie carrierWaybill z SM (ostatnie printed) ===")
        for po in sorted(orders, key=lambda x: x.order_id, reverse=True)[:15]:
            data = parse_last_order_data(po.last_order_data)
            for pkg_id in data.get("package_ids") or []:
                try:
                    details = get_shipment_details(pkg_id)
                    for pkg in details.get("packages") or []:
                        for info in pkg.get("transportingInfo") or []:
                            cw = info.get("carrierWaybill")
                            if cw:
                                print(f"  {po.order_id[:40]:40} | {info.get('carrierId'):6} | {cw}")
                except Exception:
                    pass
        failed_bc = ["2102413302196", "2LPL02495+83545000", "JJD000030230864000435460935"]
        print("\n=== Szukaj w last_order_data ===")
        for po in orders:
            raw = json.dumps(parse_last_order_data(po.last_order_data), ensure_ascii=False)
            for needle in failed_bc:
                if needle in raw:
                    print(f"  exact {needle} in {po.order_id}")


if __name__ == "__main__":
    main()
