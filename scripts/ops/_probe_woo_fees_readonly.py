"""Readonly probe: WooPayments transactions + optional ShipX calculate."""
from __future__ import annotations

import json
import sys

from sqlalchemy import desc

from magazyn.db import get_session
from magazyn.models.orders import Order
from magazyn.woocommerce_api import WooClient, WooClientError


def main() -> int:
    from magazyn.db import configure_engine

    configure_engine()
    with get_session() as db:
        order = (
            db.query(Order)
            .filter(Order.order_id.like("woo_%"))
            .filter(Order.payment_method_cod.is_(False))
            .order_by(desc(Order.date_add))
            .first()
        )
        if order is None:
            print("NO_WOO_ORDER")
            return 1
        print(
            "ORDER",
            order.order_id,
            order.external_order_id,
            order.payment_method,
            order.payment_done,
            order.delivery_method,
        )
        oid = order.external_order_id
        order_data = {
            "order_id": order.order_id,
            "delivery_method": order.delivery_method,
            "delivery_point_id": order.delivery_point_id,
            "delivery_fullname": order.delivery_fullname,
            "customer": order.customer_name,
            "email": order.email,
            "phone": order.phone,
            "delivery_address": order.delivery_address,
            "delivery_city": order.delivery_city,
            "delivery_postcode": order.delivery_postcode,
            "delivery_country_code": order.delivery_country_code or "PL",
            "payment_method_cod": "1" if order.payment_method_cod else "0",
            "payment_done": float(order.payment_done or 0),
        }

    client = WooClient()
    try:
        tx = client.get(
            "wp-json/wc/v3/payments/reports/transactions",
            params={"order_id": str(oid), "per_page": 5},
        )
    except WooClientError as exc:
        print("TX_ERR", exc.status_code, str(exc)[:400])
        tx = None
    except Exception as exc:
        print("TX_ERR", type(exc).__name__, str(exc)[:400])
        tx = None

    if isinstance(tx, list):
        print("TX_COUNT", len(tx))
        if tx:
            t0 = tx[0]
            print("TX0", json.dumps({
                "fees": t0.get("fees"),
                "amount": t0.get("amount"),
                "net_amount": t0.get("net_amount"),
                "type": t0.get("type"),
                "payment_method": t0.get("payment_method"),
                "currency": t0.get("transaction_currency") or t0.get("currency"),
            }, ensure_ascii=False))
    elif isinstance(tx, dict):
        print("TX_DICT", json.dumps({k: tx.get(k) for k in list(tx)[:15]}, ensure_ascii=False)[:800])
    else:
        print("TX_EMPTY", tx)

    # ShipX calculate — readonly; may fail for debit
    try:
        from magazyn.inpost_api.shipx import InpostShipxClient, build_shipment_payload

        payload = build_shipment_payload(order_data)
        payload["id"] = order_data["order_id"]
        client_sx = InpostShipxClient()
        rows = client_sx.calculate_shipments([payload]) if hasattr(client_sx, "calculate_shipments") else None
        if rows is None:
            rows = client_sx.request(
                "POST",
                f"/v1/organizations/{client_sx.organization_id}/shipments/calculate",
                json={"shipments": [payload]},
            )
            if isinstance(rows, dict):
                rows = rows.get("shipments") or [rows]
        print("SHIPX_CALC", json.dumps((rows or [])[:1], ensure_ascii=False)[:600])
        if rows:
            row = rows[0]
            print(
                "SHIPX_PRICE",
                row.get("calculated_charge_amount"),
                row.get("rate"),
                (row.get("selected_offer") or {}).get("rate") if isinstance(row, dict) else None,
            )
    except Exception as exc:
        print("SHIPX_ERR", type(exc).__name__, str(exc)[:400])

    return 0


if __name__ == "__main__":
    sys.exit(main())
