#!/usr/bin/env python3
"""Powiaz recznie utworzona przesylke Allegro z zamowieniem lokalnym (bez druku)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from magazyn.allegro_api.fulfillment import get_shipment_tracking_numbers
from magazyn.db import configure_engine, get_session
from magazyn.models.orders import Order, OrderStatusLog
from magazyn.services.order_status import add_order_status
from sqlalchemy import desc, text


def _resolve_checkout_form_id(order_id: str) -> str:
    if order_id.startswith("allegro_"):
        return order_id[len("allegro_") :]
    return order_id


def link_manual_shipment(
    order_id: str,
    *,
    target_status: str = "wyslano",
    dry_run: bool = False,
) -> dict:
    checkout_form_id = _resolve_checkout_form_id(order_id)
    shipments = get_shipment_tracking_numbers(checkout_form_id)
    if not shipments:
        raise RuntimeError(f"Brak przesylek w Allegro dla checkout-form {checkout_form_id}")

    shipment = shipments[0]
    waybill = shipment.get("waybill") or ""
    carrier_id = shipment.get("carrierId") or ""
    if not waybill:
        raise RuntimeError(f"Przesylka bez waybill: {json.dumps(shipment, ensure_ascii=False)}")

    result = {
        "order_id": order_id,
        "checkout_form_id": checkout_form_id,
        "waybill": waybill,
        "carrier_id": carrier_id,
        "target_status": target_status,
        "dry_run": dry_run,
    }

    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            raise RuntimeError(f"Nie znaleziono zamowienia {order_id}")

        latest = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order_id)
            .order_by(desc(OrderStatusLog.timestamp))
            .first()
        )
        result["previous_status"] = latest.status if latest else None

        if dry_run:
            result["would_update"] = {
                "courier_code": carrier_id,
                "delivery_package_nr": waybill,
                "status": target_status,
            }
            return result

        order.courier_code = carrier_id
        order.delivery_package_nr = waybill

        add_order_status(
            db,
            order_id,
            target_status,
            courier_code=carrier_id,
            tracking_number=waybill,
            notes="Reczna przesylka z Allegro - paczka juz nadana",
            send_email=False,
        )

        printed_at = datetime.now(timezone.utc).isoformat()
        db.execute(
            text(
                "INSERT INTO printed_orders(order_id, printed_at, last_order_data) "
                "VALUES (:oid, :ts, :data) "
                "ON CONFLICT(order_id) DO UPDATE SET last_order_data = excluded.last_order_data"
            ),
            {
                "oid": order_id,
                "ts": printed_at,
                "data": json.dumps(
                    {
                        "courier_code": carrier_id,
                        "delivery_package_nr": waybill,
                        "manual_shipment": True,
                        "skip_print": True,
                    }
                ),
            },
        )

        db.execute(
            text("DELETE FROM agent_state WHERE key = :k"),
            {"k": f"sm_shipment:{order_id}"},
        )

        db.commit()

        latest_after = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order_id)
            .order_by(desc(OrderStatusLog.timestamp))
            .first()
        )
        result["current_status"] = latest_after.status if latest_after else None

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("order_id")
    parser.add_argument("--status", default="wyslano")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_engine()
    result = link_manual_shipment(args.order_id, target_status=args.status, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
