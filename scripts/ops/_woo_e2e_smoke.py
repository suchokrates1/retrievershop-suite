"""Smoke E2E: Woo ping, import order, content sync sample, ShipX org, printable queue."""
from __future__ import annotations

import json
import sys


def main() -> int:
    from magazyn.factory import create_app
    from magazyn.woocommerce_api import WooClient
    from magazyn.services.woo_order_sync import import_woo_order_by_id
    from magazyn.services.allegro_offer_content import sync_linked_offers_content
    from magazyn.services.woo_catalog_sync import sync_catalog_to_woo
    from magazyn.inpost_api.shipx import InpostShipxClient, build_shipment_payload
    from magazyn.services.print_agent_orders import collect_printable_orders
    from magazyn.db import get_session
    from magazyn.models.orders import Order

    woo_id = int(sys.argv[1]) if len(sys.argv) > 1 else 3415
    app = create_app()
    with app.app_context():
        client = WooClient()
        orders = client.get(
            "wp-json/wc/v3/orders",
            params={"per_page": 1, "status": "processing"},
        )
        print("woo_ping", "ok", "sample_id", (orders[0]["id"] if orders else None))

        result = import_woo_order_by_id(woo_id)
        print("import", result)

        content = sync_linked_offers_content(limit=3, force=False)
        print("content_sync", content)

        catalog = sync_catalog_to_woo(limit=1, refresh_content=True)
        print("catalog_sync", catalog)

        shipx = InpostShipxClient()
        org = shipx.request("GET", f"/v1/organizations/{shipx.organization_id}")
        print("shipx_org", org.get("id"), org.get("name"))

        with get_session() as db:
            order = db.query(Order).filter(Order.order_id == f"woo_{woo_id}").first()
            if not order:
                print("order_missing")
                return 1
            payload = {
                "order_id": order.order_id,
                "delivery_fullname": order.delivery_fullname,
                "email": order.email,
                "phone": order.phone,
                "delivery_point_id": order.delivery_point_id,
                "delivery_method": order.delivery_method,
                "delivery_address": order.delivery_address,
                "delivery_city": order.delivery_city,
                "delivery_postcode": order.delivery_postcode,
                "delivery_country_code": order.delivery_country_code,
                "payment_method_cod": order.payment_method_cod,
                "payment_done": float(order.payment_done or 0),
            }
            ship_payload = build_shipment_payload(payload)
            print("shipx_payload_service", ship_payload.get("service"))
            print(
                "shipx_payload_point",
                (ship_payload.get("custom_attributes") or {}).get("target_point"),
            )
            print(
                "order_summary",
                json.dumps(
                    {
                        "order_id": order.order_id,
                        "customer": order.delivery_fullname,
                        "status_package": order.delivery_package_nr,
                        "point": order.delivery_point_id,
                        "method": order.delivery_method,
                        "payment": float(order.payment_done or 0),
                    },
                    ensure_ascii=False,
                ),
            )

        printable = [o["order_id"] for o in collect_printable_orders(days=30)]
        print(
            "printable_has_woo",
            f"woo_{woo_id}" in printable,
            "printable_count",
            len(printable),
        )
        print("allegro_still_queued", any(x.startswith("allegro_") for x in printable))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
