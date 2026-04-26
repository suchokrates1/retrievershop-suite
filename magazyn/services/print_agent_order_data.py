"""Budowanie danych zamowienia dla agenta drukowania."""

from __future__ import annotations

from typing import Any, Dict, List

from ..parsing import parse_product_info


def build_last_order_data(order: Dict[str, Any]) -> Dict[str, Any]:
    """Zbuduj strukturę last_order_data uzywana przez druk, historie i Messenger."""
    product_name, size, color = parse_product_info((order.get("products") or [{}])[0])
    order_id = str(order["order_id"])

    return {
        "order_id": order_id,
        "external_order_id": order.get("external_order_id", ""),
        "shop_order_id": order.get("shop_order_id"),
        "name": product_name,
        "size": size,
        "color": color,
        "customer": order.get("delivery_fullname", "Nieznany klient"),
        "email": order.get("email", ""),
        "phone": order.get("phone", ""),
        "user_login": order.get("user_login", ""),
        "platform": order.get("order_source", "brak"),
        "order_source_id": order.get("order_source_id"),
        "order_status_id": order.get("order_status_id"),
        "confirmed": order.get("confirmed", False),
        "date_add": order.get("date_add"),
        "date_confirmed": order.get("date_confirmed"),
        "date_in_status": order.get("date_in_status"),
        "shipping": order.get("delivery_method", "brak"),
        "delivery_method_id": order.get("delivery_method_id"),
        "delivery_price": order.get("delivery_price", 0),
        "delivery_fullname": order.get("delivery_fullname", ""),
        "delivery_company": order.get("delivery_company", ""),
        "delivery_address": order.get("delivery_address", ""),
        "delivery_city": order.get("delivery_city", ""),
        "delivery_postcode": order.get("delivery_postcode", ""),
        "delivery_country": order.get("delivery_country", ""),
        "delivery_country_code": order.get("delivery_country_code", ""),
        "delivery_point_id": order.get("delivery_point_id", ""),
        "delivery_point_name": order.get("delivery_point_name", ""),
        "delivery_point_address": order.get("delivery_point_address", ""),
        "delivery_point_postcode": order.get("delivery_point_postcode", ""),
        "delivery_point_city": order.get("delivery_point_city", ""),
        "invoice_fullname": order.get("invoice_fullname", ""),
        "invoice_company": order.get("invoice_company", ""),
        "invoice_nip": order.get("invoice_nip", ""),
        "invoice_address": order.get("invoice_address", ""),
        "invoice_city": order.get("invoice_city", ""),
        "invoice_postcode": order.get("invoice_postcode", ""),
        "invoice_country": order.get("invoice_country", ""),
        "want_invoice": order.get("want_invoice", "0"),
        "currency": order.get("currency", "PLN"),
        "payment_method": order.get("payment_method", ""),
        "payment_method_cod": order.get("payment_method_cod", "0"),
        "payment_done": order.get("payment_done", 0),
        "user_comments": order.get("user_comments", ""),
        "admin_comments": order.get("admin_comments", ""),
        "products": order.get("products", []),
        "courier_code": "",
        "delivery_package_module": order.get("delivery_package_module", ""),
        "delivery_package_nr": order.get("delivery_package_nr", ""),
        "package_ids": [],
        "tracking_numbers": [],
    }


def apply_package_tracking(
    last_order_data: Dict[str, Any],
    *,
    courier_code: str,
    package_ids: List[str],
    tracking_numbers: List[str],
) -> None:
    """Uzupelnij last_order_data o dane paczek i numerow trackingowych."""
    if courier_code:
        last_order_data["courier_code"] = courier_code
    if package_ids:
        last_order_data["package_ids"] = list(dict.fromkeys(package_ids))
    if tracking_numbers:
        last_order_data["tracking_numbers"] = list(dict.fromkeys(tracking_numbers))
        last_order_data["delivery_package_nr"] = tracking_numbers[0]


__all__ = ["apply_package_tracking", "build_last_order_data"]