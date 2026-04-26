"""Helpery budowania przesylek Allegro dla agenta drukowania."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .print_agent_config import calculate_cod_amount, is_cod_order


def shorten_product_name(full_name: str) -> str:
    words = full_name.strip().split()
    if len(words) >= 3:
        return f"{words[0]} {' '.join(words[-2:])}"
    return full_name


def resolve_carrier_id(delivery_method: str) -> Optional[str]:
    """Mapuj nazwe metody dostawy na carrier_id Allegro."""
    if not delivery_method:
        return None

    method_lower = delivery_method.lower()
    carrier_map = {
        "inpost": "INPOST",
        "paczkomat": "INPOST",
        "dhl": "DHL",
        "dpd": "DPD",
        "poczta": "POCZTA_POLSKA",
        "pocztex": "POCZTA_POLSKA",
        "ups": "UPS",
        "gls": "GLS",
        "fedex": "FEDEX",
        "orlen": "ALLEGRO",
        "allegro one": "ALLEGRO",
        "allegro kurier": "ALLEGRO",
        "allegro automat": "ALLEGRO",
    }

    for key, carrier_id in carrier_map.items():
        if key in method_lower:
            return carrier_id

    return "OTHER"


def build_sender(settings_store: Any) -> Dict[str, str]:
    """Zbuduj dane nadawcy z ustawien aplikacji."""
    sender = {
        "name": settings_store.get("SENDER_NAME") or "Alexandra Kaługa",
        "street": settings_store.get("SENDER_STREET") or "",
        "postalCode": settings_store.get("SENDER_ZIPCODE") or "",
        "city": settings_store.get("SENDER_CITY") or "",
        "countryCode": "PL",
        "phone": settings_store.get("SENDER_PHONE") or "",
        "email": settings_store.get("SENDER_EMAIL") or "",
    }
    sender_company = settings_store.get("SENDER_COMPANY") or "Retriever Shop"
    if sender_company:
        sender["company"] = sender_company[:30]
    return sender


def build_receiver(order_data: Dict[str, Any]) -> Dict[str, str]:
    """Zbuduj dane odbiorcy z danych zamowienia."""
    receiver = {
        "name": order_data.get("delivery_fullname", ""),
        "street": order_data.get("delivery_address", ""),
        "postalCode": order_data.get("delivery_postcode", ""),
        "city": order_data.get("delivery_city", ""),
        "countryCode": order_data.get("delivery_country_code", "PL"),
        "email": order_data.get("email", ""),
        "phone": order_data.get("phone", ""),
    }

    point_id = order_data.get("delivery_point_id", "")
    if point_id:
        receiver["point"] = point_id

    return receiver


def choose_package_dimensions(products: List[Dict[str, Any]]) -> Dict[str, int]:
    """Dobierz gabaryt paczki na podstawie lacznej liczby produktow."""
    total_qty = sum(product.get("quantity", 1) for product in products)
    if total_qty > 5:
        return {"length": 64, "width": 38, "height": 19}
    return {"length": 64, "width": 38, "height": 8}


def build_label_references(products: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """Zbuduj textOnLabel i referenceNumber zgodne z limitami Allegro."""
    product_names = []
    for product in products:
        name = shorten_product_name(product.get("name", ""))
        quantity = product.get("quantity", 1)
        attributes = product.get("attributes", "")
        label = name
        if attributes:
            label = f"{name} ({attributes})"
        if quantity > 1:
            label = f"{label} x{quantity}"
        if label:
            product_names.append(label)

    if not product_names:
        return None, None

    raw_ref = "; ".join(product_names)
    normalized = unicodedata.normalize("NFKD", raw_ref)
    ascii_ref = "".join(char for char in normalized if not unicodedata.combining(char))
    sanitized = re.sub(r"[^a-zA-Z0-9 _/\-]", "", ascii_ref)
    label_text = sanitized[:30]
    return label_text, label_text


def build_packages(products: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Zbuduj payload paczek i referenceNumber dla Shipment Management."""
    dimensions = choose_package_dimensions(products)
    text_on_label, reference_number = build_label_references(products)

    package = {
        "type": "PACKAGE",
        "weight": {"value": 1.0, "unit": "KILOGRAMS"},
        "length": {"value": dimensions["length"], "unit": "CENTIMETER"},
        "width": {"value": dimensions["width"], "unit": "CENTIMETER"},
        "height": {"value": dimensions["height"], "unit": "CENTIMETER"},
    }
    if text_on_label:
        package["textOnLabel"] = text_on_label

    return [package], reference_number


def build_additional_services(carrier_id: Optional[str]) -> Optional[List[str]]:
    """Zwroc dodatkowe uslugi dla przewoznika."""
    if carrier_id == "INPOST":
        return ["sendingAtPoint"]
    return None


def build_cod_payload(order_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Zbuduj payload pobrania dla zamowien COD."""
    if not is_cod_order(
        order_data.get("payment_method_cod", "0"),
        order_data.get("payment_method", ""),
    ):
        return None

    cod_amount = calculate_cod_amount(order_data)
    if cod_amount <= 0:
        return None

    return {"amount": str(cod_amount), "currency": "PLN"}


__all__ = [
    "build_additional_services",
    "build_cod_payload",
    "build_label_references",
    "build_packages",
    "build_receiver",
    "build_sender",
    "choose_package_dimensions",
    "resolve_carrier_id",
    "shorten_product_name",
]