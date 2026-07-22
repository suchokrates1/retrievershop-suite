"""Koszt wysyłki sklepu (InPost) — osobny od Allegro Smart."""

from __future__ import annotations

import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from ..settings_store import settings_store

logger = logging.getLogger(__name__)

TWOPLACES = Decimal("0.01")

# Publiczne stawki InPost (detal, od 2026-03) — fallback gdy ShipX nie zwraca ceny
DEFAULT_LOCKER = {
    "A": Decimal("16.49"),
    "B": Decimal("18.49"),
    "C": Decimal("20.49"),
}
DEFAULT_COURIER = {
    "A": Decimal("19.49"),
    "B": Decimal("20.49"),
    "C": Decimal("25.49"),
}

TEMPLATE_TO_SIZE = {
    "small": "A",
    "a": "A",
    "medium": "B",
    "b": "B",
    "large": "C",
    "c": "C",
}


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except Exception:
        return default


def _settings_cost(key: str, default: Decimal) -> Decimal:
    raw = settings_store.get(key)
    if raw is None or raw == "":
        return default
    return _to_decimal(raw, default)


def resolve_parcel_size(template_or_method: Optional[str] = None) -> str:
    text = (template_or_method or "small").strip().lower()
    if text in TEMPLATE_TO_SIZE:
        return TEMPLATE_TO_SIZE[text]
    if "gabaryt c" in text or text.endswith("_c") or " large" in text:
        return "C"
    if "gabaryt b" in text or text.endswith("_b") or " medium" in text:
        return "B"
    return "A"


def is_locker_delivery(order_or_method: Any = None, point_id: Optional[str] = None) -> bool:
    if point_id:
        return True
    if order_or_method is None:
        return False
    if hasattr(order_or_method, "delivery_point_id"):
        if getattr(order_or_method, "delivery_point_id", None):
            return True
        method = getattr(order_or_method, "delivery_method", None) or ""
    else:
        method = str(order_or_method or "")
    lower = method.lower()
    return "paczkomat" in lower or "locker" in lower or "parcel_machine" in lower


def estimate_shop_shipping_cost(
    order=None,
    *,
    delivery_method: Optional[str] = None,
    point_id: Optional[str] = None,
    parcel_template: str = "small",
) -> dict[str, Any]:
    """Szacunek kosztu InPost sprzedawcy (settings, nie Allegro Smart)."""
    method = delivery_method
    pid = point_id
    if order is not None:
        method = method or getattr(order, "delivery_method", None)
        pid = pid or getattr(order, "delivery_point_id", None)

    size = resolve_parcel_size(parcel_template)
    locker = is_locker_delivery(order if order is not None else method, pid)
    if locker:
        key = f"INPOST_SHOP_LOCKER_{size}"
        cost = _settings_cost(key, DEFAULT_LOCKER[size])
        channel = "locker"
    else:
        key = f"INPOST_SHOP_COURIER_{size}"
        cost = _settings_cost(key, DEFAULT_COURIER[size])
        channel = "courier"

    return {
        "cost": cost,
        "source": "estimated",
        "is_estimated": True,
        "channel": channel,
        "size": size,
        "settings_key": key,
    }


def extract_rate_from_shipment(details: dict) -> Optional[Decimal]:
    """Wyciągnij cenę z odpowiedzi ShipX (selected_offer / offers)."""
    selected = details.get("selected_offer") or {}
    rate = selected.get("rate")
    if rate is not None:
        return _to_decimal(rate)

    for offer in details.get("offers") or []:
        if not isinstance(offer, dict):
            continue
        if offer.get("rate") is not None:
            return _to_decimal(offer["rate"])
    return None


def parse_order_products_payload(products_json: Optional[str]) -> tuple[list, dict]:
    """Zwraca (products_list, meta_dict). Obsługuje listę lub {"products","meta"}."""
    if not products_json:
        return [], {}
    try:
        data = json.loads(products_json)
    except Exception:
        return [], {}
    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict):
        products = data.get("products")
        if products is None and "meta" not in data and "seller_shipping_cost" not in (
            data.get("meta") or {}
        ):
            # stary format dict bez products — traktuj jako puste
            products = data.get("items") or []
        meta = data.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        return list(products or []), meta
    return [], {}


def dump_order_products_payload(products: list, meta: Optional[dict] = None) -> str:
    meta = meta or {}
    if meta:
        return json.dumps({"products": products, "meta": meta}, ensure_ascii=False)
    return json.dumps(products, ensure_ascii=False)


def get_stored_seller_shipping(order) -> Optional[dict[str, Any]]:
    _, meta = parse_order_products_payload(getattr(order, "products_json", None))
    if "seller_shipping_cost" not in meta:
        return None
    return {
        "cost": _to_decimal(meta.get("seller_shipping_cost")),
        "source": meta.get("seller_shipping_source") or "api",
        "is_estimated": False,
    }


def store_seller_shipping_on_order(
    order,
    cost: Decimal,
    *,
    source: str = "api",
) -> None:
    """Zapisz koszt wysyłki sprzedawcy w products_json.meta (bez migracji)."""
    products, meta = parse_order_products_payload(getattr(order, "products_json", None))
    meta["seller_shipping_cost"] = str(_to_decimal(cost))
    meta["seller_shipping_source"] = source
    order.products_json = dump_order_products_payload(products, meta)


def resolve_seller_shipping_cost(order) -> dict[str, Any]:
    """Preferuj zapisany koszt API, inaczej estymata settings."""
    stored = get_stored_seller_shipping(order)
    if stored is not None:
        return {
            "cost": stored["cost"],
            "source": stored["source"],
            "is_estimated": False,
            "channel": None,
            "size": None,
            "settings_key": None,
        }
    return estimate_shop_shipping_cost(order)


__all__ = [
    "DEFAULT_COURIER",
    "DEFAULT_LOCKER",
    "dump_order_products_payload",
    "estimate_shop_shipping_cost",
    "extract_rate_from_shipment",
    "get_stored_seller_shipping",
    "is_locker_delivery",
    "parse_order_products_payload",
    "resolve_parcel_size",
    "resolve_seller_shipping_cost",
    "store_seller_shipping_on_order",
]
