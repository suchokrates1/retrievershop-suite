"""Synchronizacja danych zamówienia z payloadu integracji."""

from __future__ import annotations

import json
import logging
import re
import secrets
import unicodedata
from collections.abc import Callable
from typing import Optional

from sqlalchemy import func

from ..models import Order, OrderProduct, OrderStatusLog, Product, ProductSize
from .order_status import add_order_status


logger = logging.getLogger(__name__)


def _strip_diacritics_ord(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


_COLOR_CANONICAL_MAP = {
    "pomaranczowy": "pomaranczowy",
    "pomaranczowe": "pomaranczowy",
    "pomaranczowa": "pomaranczowy",
    "brazowy": "brazowy",
    "brazowe": "brazowy",
    "brazowa": "brazowy",
    "zolty": "zolty",
    "zolte": "zolty",
    "zolta": "zolty",
    "czarny": "czarny",
    "czarne": "czarny",
    "czarna": "czarny",
    "czerwony": "czerwony",
    "czerwone": "czerwony",
    "czerwona": "czerwony",
    "niebieski": "niebieski",
    "niebieskie": "niebieski",
    "niebieska": "niebieski",
    "zielony": "zielony",
    "zielone": "zielony",
    "zielona": "zielony",
    "rozowy": "rozowy",
    "rozowe": "rozowy",
    "rozowa": "rozowy",
    "fioletowy": "fioletowy",
    "fioletowe": "fioletowy",
    "fioletowa": "fioletowy",
    "srebrny": "srebrny",
    "srebrne": "srebrny",
    "srebrna": "srebrny",
    "granatowy": "granatowy",
    "granatowe": "granatowy",
    "granatowa": "granatowy",
    "szary": "szary",
    "szare": "szary",
    "szara": "szary",
    "turkusowy": "turkusowy",
    "turkusowe": "turkusowy",
    "turkusowa": "turkusowy",
    "bialy": "bialy",
    "biale": "bialy",
    "biala": "bialy",
    "blekitny": "blekitny",
    "blekitne": "blekitny",
    "blekitna": "blekitny",
    "limonkowy": "limonkowy",
    "limonkowe": "limonkowy",
    "limonkowa": "limonkowy",
}


def _normalize_color_key(color: str) -> str:
    if not color:
        return ""
    stripped = _strip_diacritics_ord(color).lower().strip()
    return _COLOR_CANONICAL_MAP.get(stripped, stripped)


def _extract_series_from_name(product_name: str) -> str:
    if not product_name:
        return ""
    match = re.search(r"Truelove\s+(.+)", product_name, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return product_name


def match_product_to_warehouse(db, name: str, color: str, size: str) -> Optional[ProductSize]:
    """Dopasuj produkt z zamówienia do rozmiaru produktu w magazynie."""
    series = _extract_series_from_name(name)
    if not series:
        return None

    series_norm = _strip_diacritics_ord(series).lower()
    color_norm = _normalize_color_key(color)
    size_upper = size.upper() if size else size
    candidates = (
        db.query(ProductSize)
        .join(Product)
        .filter(func.upper(ProductSize.size) == size_upper)
        .all()
    )

    for product_size in candidates:
        product = product_size.product
        db_series = _strip_diacritics_ord(product.series or "").lower()
        db_color = _normalize_color_key(product.color or "")

        if series_norm == db_series and color_norm == db_color:
            return product_size

    for product_size in candidates:
        product = product_size.product
        db_series = _strip_diacritics_ord(product.series or "").lower()
        db_color = _normalize_color_key(product.color or "")

        if (
            db_series
            and (db_series in series_norm or series_norm in db_series)
            and color_norm == db_color
        ):
            return product_size

    if not color_norm:
        series_matches = []
        for product_size in candidates:
            product = product_size.product
            db_series = _strip_diacritics_ord(product.series or "").lower()
            if db_series and (
                series_norm == db_series
                or db_series in series_norm
                or series_norm in db_series
            ):
                db_name_norm = _strip_diacritics_ord(product.name or "").lower()
                name_norm = _strip_diacritics_ord(name or "").lower()
                if (
                    db_name_norm == name_norm
                    or db_name_norm in name_norm
                    or name_norm in db_name_norm
                ):
                    series_matches.append(product_size)
        if len(series_matches) == 1:
            return series_matches[0]

    return None


def _merge_products(products_list: list[dict]) -> list[dict]:
    merged_products = {}
    for product in products_list:
        key = (
            str(product.get("auction_id") or "").strip(),
            str(product.get("ean") or "").strip(),
            str(product.get("sku") or "").strip(),
            str(product.get("name") or "").strip(),
            str(product.get("price_brutto") or "").strip(),
        )

        quantity = product.get("quantity", 1)
        try:
            quantity_int = int(quantity)
        except (TypeError, ValueError):
            quantity_int = 1

        if key not in merged_products:
            merged = dict(product)
            merged["quantity"] = max(1, quantity_int)
            merged_products[key] = merged
        else:
            merged_products[key]["quantity"] = (
                int(merged_products[key].get("quantity", 1)) + max(1, quantity_int)
            )

    return list(merged_products.values())


def sync_order_from_data(
    db,
    order_data: dict,
    *,
    add_status: Callable[..., Optional[OrderStatusLog]] = add_order_status,
) -> Order:
    """Utwórz lub zaktualizuj zamówienie na podstawie danych z integracji."""
    order_id = str(order_data.get("order_id"))
    external_order_id = order_data.get("external_order_id")

    order = db.query(Order).filter(Order.order_id == order_id).first()
    is_new_order = False

    if not order:
        if external_order_id:
            existing = (
                db.query(Order)
                .filter(Order.external_order_id == external_order_id)
                .first()
            )
            if existing:
                order = existing
                is_new_order = False

        if not order:
            order = Order(order_id=order_id)
            order.customer_token = secrets.token_urlsafe(32)
            db.add(order)
            is_new_order = True

    order_id = order.order_id

    order.external_order_id = order_data.get("external_order_id")
    order.shop_order_id = order_data.get("shop_order_id")
    order.customer_name = order_data.get("customer") or order_data.get("delivery_fullname")
    order.email = order_data.get("email")
    order.phone = order_data.get("phone")
    order.user_login = order_data.get("user_login")
    order.platform = order_data.get("platform")
    order.order_source_id = order_data.get("order_source_id")
    order.order_status_id = order_data.get("order_status_id")
    order.confirmed = order_data.get("confirmed", False)
    order.date_add = order_data.get("date_add")
    order.date_confirmed = order_data.get("date_confirmed")
    order.date_in_status = order_data.get("date_in_status")
    order.delivery_method = order_data.get("shipping") or order_data.get("delivery_method")
    order.delivery_method_id = order_data.get("delivery_method_id")
    order.delivery_price = order_data.get("delivery_price")
    order.delivery_fullname = order_data.get("delivery_fullname")
    order.delivery_company = order_data.get("delivery_company")
    order.delivery_address = order_data.get("delivery_address")
    order.delivery_city = order_data.get("delivery_city")
    order.delivery_postcode = order_data.get("delivery_postcode")
    order.delivery_country = order_data.get("delivery_country")
    order.delivery_country_code = order_data.get("delivery_country_code")
    order.delivery_point_id = order_data.get("delivery_point_id")
    order.delivery_point_name = order_data.get("delivery_point_name")
    order.delivery_point_address = order_data.get("delivery_point_address")
    order.delivery_point_postcode = order_data.get("delivery_point_postcode")
    order.delivery_point_city = order_data.get("delivery_point_city")
    order.invoice_fullname = order_data.get("invoice_fullname")
    order.invoice_company = order_data.get("invoice_company")
    order.invoice_nip = order_data.get("invoice_nip")
    order.invoice_address = order_data.get("invoice_address")
    order.invoice_city = order_data.get("invoice_city")
    order.invoice_postcode = order_data.get("invoice_postcode")
    order.invoice_country = order_data.get("invoice_country")
    order.want_invoice = order_data.get("want_invoice") == "1"
    order.currency = order_data.get("currency", "PLN")
    order.payment_method = order_data.get("payment_method")
    cod_value = order_data.get("payment_method_cod")
    order.payment_method_cod = cod_value in ("1", True, 1)
    order.payment_done = order_data.get("payment_done")
    order.user_comments = order_data.get("user_comments")
    order.admin_comments = order_data.get("admin_comments")

    incoming_courier_code = order_data.get("courier_code")
    if incoming_courier_code:
        order.courier_code = incoming_courier_code
    order.delivery_package_module = order_data.get("delivery_package_module")
    incoming_delivery_package_nr = order_data.get("delivery_package_nr")
    if incoming_delivery_package_nr:
        order.delivery_package_nr = incoming_delivery_package_nr

    raw_products_list = order_data.get("products", [])
    order.products_json = json.dumps(raw_products_list) if raw_products_list else None
    products_list = _merge_products(raw_products_list)

    if order.payment_method_cod and float(order.payment_done or 0) == 0:
        total_products = sum(
            float(product.get("price_brutto", 0)) * int(product.get("quantity", 1))
            for product in products_list
        )
        delivery = float(order.delivery_price or 0)
        order.payment_done = total_products + delivery
        logger.info(
            "Zamowienie COD %s - ustawiam payment_done=%.2f "
            "(produkty=%.2f + dostawa=%.2f)",
            order_id,
            order.payment_done,
            total_products,
            delivery,
        )

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.flush()
        db.query(Order).filter(Order.order_id == order_id).with_for_update().first()

    db.query(OrderProduct).filter(OrderProduct.order_id == order_id).delete(
        synchronize_session=False
    )

    for product in products_list:
        ean = product.get("ean", "").strip() or None
        product_size_id = None

        if ean:
            product_size = db.query(ProductSize).filter(ProductSize.barcode == ean).first()
            if product_size:
                product_size_id = product_size.id

        if not product_size_id:
            from ..parsing import parse_product_info

            name, size, color = parse_product_info(product)

            if name and size:
                product_size = match_product_to_warehouse(db, name, color, size)
                if product_size:
                    product_size_id = product_size.id
                    logger.info(
                        "Matched: %s -> %s/%s/%s -> product_size_id=%s",
                        product.get("name"),
                        name,
                        color,
                        size,
                        product_size.id,
                    )
                else:
                    logger.warning(
                        "NOT MATCHED: %s -> parsed: %s/%s/%s",
                        product.get("name"),
                        name,
                        color or "(brak)",
                        size,
                    )
            else:
                logger.warning(
                    "NOT MATCHED (parse failed): %s -> name=%s, size=%s, color=%s",
                    product.get("name"),
                    name,
                    size,
                    color,
                )

        db.add(
            OrderProduct(
                order_id=order_id,
                order_product_id=product.get("order_product_id"),
                product_id=product.get("product_id"),
                variant_id=product.get("variant_id"),
                sku=product.get("sku"),
                ean=ean,
                name=product.get("name"),
                quantity=product.get("quantity", 1),
                price_brutto=product.get("price_brutto"),
                auction_id=product.get("auction_id"),
                attributes=product.get("attributes"),
                location=product.get("location"),
                product_size_id=product_size_id,
            )
        )

    db.flush()

    try:
        from ..domain.financial import FinancialCalculator
        from ..settings_store import settings_store

        FinancialCalculator(db, settings_store).refresh_order_profit_cache(
            order,
            trace_label="sync-order",
        )
    except Exception as exc:
        logger.warning(
            "Blad odswiezenia cache realnego zysku dla %s: %s",
            order_id,
            exc,
        )

    initial_status = "pobrano"
    if (
        order_data.get("platform") == "allegro"
        or "_allegro_status" in order_data
        or "_allegro_fulfillment_status" in order_data
    ):
        from ..allegro_api.orders import get_allegro_internal_status

        initial_status = get_allegro_internal_status(order_data)

    if is_new_order:
        add_status(db, order_id, initial_status, notes="Nowe zamowienie")

    return order


__all__ = ["match_product_to_warehouse", "sync_order_from_data"]