"""Przygotowanie danych recznego zamowienia."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ManualOrderPayload:
    order_data: dict[str, Any] | None
    error: str | None = None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 1) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def build_manual_order_payload(form: Any) -> ManualOrderPayload:
    order_id = f"manual_{int(time.time())}_{secrets.token_hex(4)}"
    now_ts = int(time.time())

    commission_type = form.get("commission_type", "percent")
    commission_value = _as_float(form.get("commission_value"))

    names = form.getlist("prod_name[]")
    eans = form.getlist("prod_ean[]")
    qtys = form.getlist("prod_qty[]")
    prices = form.getlist("prod_price[]")

    products = []
    for idx, name in enumerate(names):
        if not name.strip():
            continue

        price = _as_float(prices[idx] if idx < len(prices) else 0)
        if commission_type == "percent" and commission_value > 0:
            commission_fee = round(price * commission_value / 100, 2)
        elif commission_type == "amount" and commission_value > 0:
            commission_fee = commission_value
        else:
            commission_fee = 0.0

        products.append(
            {
                "name": name.strip(),
                "ean": eans[idx].strip() if idx < len(eans) else "",
                "quantity": _as_int(qtys[idx] if idx < len(qtys) else 1),
                "price_brutto": price,
                "commission_fee": commission_fee,
            }
        )

    if not products:
        return ManualOrderPayload(order_data=None, error="Dodaj co najmniej jeden produkt.")

    customer_name = form.get("customer_name", "").strip()
    order_data = {
        "order_id": order_id,
        "external_order_id": form.get("external_order_id", "").strip() or None,
        "platform": form.get("platform", "olx"),
        "customer": customer_name,
        "delivery_fullname": form.get("delivery_fullname", "").strip() or customer_name,
        "email": form.get("email", "").strip() or None,
        "phone": form.get("phone", "").strip() or None,
        "delivery_company": form.get("delivery_company", "").strip() or None,
        "delivery_address": form.get("delivery_address", "").strip(),
        "delivery_postcode": form.get("delivery_postcode", "").strip() or None,
        "delivery_city": form.get("delivery_city", "").strip(),
        "delivery_country": "Polska",
        "delivery_country_code": "PL",
        "delivery_method": form.get("delivery_method", ""),
        "delivery_price": _as_float(form.get("delivery_price")),
        "delivery_package_nr": form.get("delivery_package_nr", "").strip() or None,
        "delivery_point_id": form.get("delivery_point_id", "").strip() or None,
        "delivery_point_address": form.get("delivery_point_address", "").strip() or None,
        "delivery_point_city": form.get("delivery_point_city", "").strip() or None,
        "payment_method": form.get("payment_method", "przelew"),
        "payment_method_cod": "1" if form.get("payment_method") == "za_pobraniem" else "0",
        "payment_done": _as_float(form.get("payment_done")),
        "want_invoice": "1" if form.get("want_invoice") else "0",
        "invoice_fullname": form.get("invoice_fullname", "").strip() or None,
        "invoice_company": form.get("invoice_company", "").strip() or None,
        "invoice_nip": form.get("invoice_nip", "").strip() or None,
        "invoice_address": form.get("invoice_address", "").strip() or None,
        "invoice_postcode": form.get("invoice_postcode", "").strip() or None,
        "invoice_city": form.get("invoice_city", "").strip() or None,
        "invoice_country": "Polska",
        "user_comments": form.get("user_comments", "").strip() or None,
        "admin_comments": form.get("admin_comments", "").strip() or None,
        "currency": "PLN",
        "confirmed": True,
        "date_add": now_ts,
        "date_confirmed": now_ts,
        "products": products,
    }
    return ManualOrderPayload(order_data=order_data)


__all__ = ["ManualOrderPayload", "build_manual_order_payload"]