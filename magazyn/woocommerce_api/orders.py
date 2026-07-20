"""Zamowienia WooCommerce → format magazynu."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .client import WooClient

logger = logging.getLogger(__name__)


def fetch_orders(
    client: WooClient,
    *,
    status: str = "processing,completed",
    after: Optional[str] = None,
    per_page: int = 50,
) -> list[dict]:
    params: dict[str, Any] = {"status": status, "per_page": per_page, "orderby": "date", "order": "desc"}
    if after:
        params["after"] = after
    return client.get("wp-json/wc/v3/orders", params=params) or []


def fetch_order(client: WooClient, order_id: int | str) -> dict:
    return client.get(f"wp-json/wc/v3/orders/{order_id}")


def update_order_tracking(
    client: WooClient,
    order_id: int | str,
    *,
    tracking_number: str,
    carrier: str = "InPost",
    status: str = "completed",
) -> dict:
    note = f"Wyslano: {carrier} {tracking_number}"
    payload = {
        "status": status,
        "meta_data": [
            {"key": "_tracking_number", "value": tracking_number},
            {"key": "_tracking_provider", "value": carrier},
            {"key": "easypack_tracking_number", "value": tracking_number},
        ],
    }
    updated = client.put(f"wp-json/wc/v3/orders/{order_id}", json=payload)
    try:
        client.post(
            f"wp-json/wc/v3/orders/{order_id}/notes",
            json={"note": note, "customer_note": True},
        )
    except Exception as exc:
        logger.warning("Nie dodano notatki Woo do zamowienia %s: %s", order_id, exc)
    return updated


def parse_woo_order_to_data(order: dict) -> dict[str, Any]:
    """Zmapuj zamowienie Woo na dict zgodny z sync_order_from_data."""
    woo_id = order["id"]
    billing = order.get("billing") or {}
    shipping = order.get("shipping") or {}

    customer_name = (
        f"{shipping.get('first_name') or billing.get('first_name') or ''} "
        f"{shipping.get('last_name') or billing.get('last_name') or ''}"
    ).strip()

    address = shipping.get("address_1") or billing.get("address_1") or ""
    address2 = shipping.get("address_2") or billing.get("address_2") or ""
    if address2:
        address = f"{address} {address2}".strip()

    # InPost paczkomat — meta z pluginu
    point_id = ""
    point_name = ""
    for meta in order.get("meta_data") or []:
        key = (meta.get("key") or "").lower()
        value = str(meta.get("value") or "")
        if key in {"_parcel_locker", "parcel_locker", "easypack_parcel_locker", "paczkomat"}:
            point_id = value
        if "parcel_machine" in key or "paczkomat" in key:
            if not point_id:
                point_id = value
            point_name = value

    shipping_lines = order.get("shipping_lines") or []
    delivery_method = ""
    delivery_price = 0.0
    if shipping_lines:
        delivery_method = shipping_lines[0].get("method_title") or shipping_lines[0].get("method_id") or ""
        try:
            delivery_price = float(shipping_lines[0].get("total") or 0)
        except (TypeError, ValueError):
            delivery_price = 0.0

    payment_method_title = order.get("payment_method_title") or order.get("payment_method") or ""
    is_cod = "pobranie" in payment_method_title.lower() or order.get("payment_method") == "cod"

    try:
        payment_done = float(order.get("total") or 0) if order.get("date_paid") or not is_cod else 0.0
        if order.get("status") in {"processing", "completed"} and not is_cod:
            payment_done = float(order.get("total") or 0)
        if is_cod:
            payment_done = float(order.get("total") or 0)
    except (TypeError, ValueError):
        payment_done = 0.0

    products = []
    for item in order.get("line_items") or []:
        sku = (item.get("sku") or "").strip()
        products.append(
            {
                "name": item.get("name") or "",
                "ean": sku,
                "sku": sku,
                "quantity": int(item.get("quantity") or 1),
                "price_brutto": float(item.get("price") or 0),
                "auction_id": "",
            }
        )

    date_created = order.get("date_created_gmt") or order.get("date_created") or ""
    try:
        # 2026-07-20T10:00:00
        ts = int(time.mktime(time.strptime(date_created[:19], "%Y-%m-%dT%H:%M:%S")))
    except Exception:
        ts = int(time.time())

    return {
        "order_id": f"woo_{woo_id}",
        "external_order_id": str(woo_id),
        "shop_order_id": int(woo_id),
        "platform": "woocommerce",
        "customer": customer_name,
        "delivery_fullname": customer_name,
        "email": billing.get("email") or None,
        "phone": billing.get("phone") or shipping.get("phone") or None,
        "delivery_company": shipping.get("company") or billing.get("company") or None,
        "delivery_address": address,
        "delivery_postcode": shipping.get("postcode") or billing.get("postcode") or None,
        "delivery_city": shipping.get("city") or billing.get("city") or None,
        "delivery_country": shipping.get("country") or billing.get("country") or "PL",
        "delivery_country_code": shipping.get("country") or billing.get("country") or "PL",
        "delivery_method": delivery_method,
        "delivery_price": delivery_price,
        "delivery_point_id": point_id or None,
        "delivery_point_name": point_name or point_id or None,
        "payment_method": payment_method_title or ("Pobranie" if is_cod else "Przelew online"),
        "payment_method_cod": "1" if is_cod else "0",
        "payment_done": payment_done,
        "want_invoice": "1" if billing.get("company") or _meta(order, "_billing_nip") else "0",
        "invoice_company": billing.get("company") or None,
        "invoice_nip": _meta(order, "_billing_nip") or _meta(order, "nip") or None,
        "invoice_address": billing.get("address_1") or None,
        "invoice_postcode": billing.get("postcode") or None,
        "invoice_city": billing.get("city") or None,
        "invoice_country": "Polska",
        "user_comments": order.get("customer_note") or None,
        "currency": order.get("currency") or "PLN",
        "confirmed": True,
        "date_add": ts,
        "date_confirmed": ts,
        "products": products,
        "woo_status": order.get("status"),
    }


def _meta(order: dict, key: str) -> Optional[str]:
    for meta in order.get("meta_data") or []:
        if meta.get("key") == key:
            value = meta.get("value")
            return str(value) if value is not None else None
    return None
