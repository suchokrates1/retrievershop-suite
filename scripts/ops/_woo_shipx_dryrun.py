"""Dry-run ShipX: create shipment + fetch label PDF, then cancel if possible."""
from __future__ import annotations

import sys


def main() -> int:
    from magazyn.factory import create_app
    from magazyn.db import get_session
    from magazyn.models.orders import Order
    from magazyn.inpost_api.shipx import InpostShipxClient, create_shipment_and_label

    order_id = sys.argv[1] if len(sys.argv) > 1 else "woo_3415"
    cancel = "--keep" not in sys.argv
    app = create_app()
    with app.app_context():
        with get_session() as db:
            order = db.query(Order).filter(Order.order_id == order_id).first()
            if not order:
                print("missing", order_id)
                return 1
            order_data = {
                "order_id": order.order_id,
                "delivery_fullname": order.delivery_fullname,
                "customer": order.delivery_fullname,
                "email": order.email,
                "phone": order.phone,
                "delivery_point_id": order.delivery_point_id,
                "delivery_method": order.delivery_method,
                "delivery_address": order.delivery_address,
                "delivery_city": order.delivery_city,
                "delivery_postcode": order.delivery_postcode,
                "delivery_country_code": order.delivery_country_code or "PL",
                "payment_method_cod": order.payment_method_cod,
                "payment_done": float(order.payment_done or 0),
            }

        result = create_shipment_and_label(order_data, wait_seconds=12)
        pdf_len = len(result.get("label_pdf") or b"")
        print(
            "created",
            result.get("shipment_id"),
            "waybill",
            result.get("waybill"),
            "pdf_bytes",
            pdf_len,
        )

        if cancel and result.get("shipment_id"):
            client = InpostShipxClient()
            try:
                client.request("DELETE", f"/v1/shipments/{result['shipment_id']}")
                print("cancelled", result["shipment_id"])
            except Exception as exc:
                print("cancel_failed", exc)
                print("NOTE: shipment left active — cancel in InPost panel if needed")
        return 0 if pdf_len > 1000 else 2


if __name__ == "__main__":
    raise SystemExit(main())
