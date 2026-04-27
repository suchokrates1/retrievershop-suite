"""Pobieranie zamowien gotowych do druku dla agenta etykiet."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import desc, func

from ..db import get_session
from ..models.orders import Order, OrderStatusLog

logger = logging.getLogger(__name__)


def collect_printable_orders(
    *,
    days: int = 7,
    max_print_error_retries: int = 3,
    now: Callable[[], datetime] = datetime.now,
    log: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    """Pobierz zamowienia w statusie pobrano lub blad_druku do kolejki agenta."""
    active_logger = log or logger
    week_ago = int((now() - timedelta(days=days)).timestamp())
    orders: List[Dict[str, Any]] = []

    with get_session() as db:
        recent_orders = db.query(Order).filter(Order.date_add >= week_ago).all()

        for order in recent_orders:
            latest = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order.order_id)
                .order_by(desc(OrderStatusLog.timestamp))
                .first()
            )
            current_status = latest.status if latest else "pobrano"

            if current_status == "blad_druku":
                error_count = (
                    db.query(func.count(OrderStatusLog.id))
                    .filter(
                        OrderStatusLog.order_id == order.order_id,
                        OrderStatusLog.status == "blad_druku",
                    )
                    .scalar()
                ) or 0
                if error_count >= max_print_error_retries:
                    continue
            elif current_status != "pobrano":
                continue

            orders.append(_build_order_payload(order))

    active_logger.debug("Znaleziono %d zamowien do druku", len(orders))
    return orders


def _build_order_payload(order: Order) -> Dict[str, Any]:
    products_list = [
        {
            "name": op.name or "",
            "quantity": op.quantity or 1,
            "price_brutto": str(op.price_brutto) if op.price_brutto else "0",
            "auction_id": op.auction_id or "",
            "sku": op.sku or "",
            "ean": op.ean or "",
            "attributes": op.attributes or "",
        }
        for op in order.products
    ]

    return {
        "order_id": order.order_id,
        "external_order_id": order.external_order_id or "",
        "shop_order_id": order.shop_order_id,
        "delivery_fullname": order.delivery_fullname or "",
        "email": order.email or "",
        "phone": order.phone or "",
        "user_login": order.user_login or "",
        "order_source": order.platform or "allegro",
        "order_source_id": order.order_source_id,
        "order_status_id": order.order_status_id,
        "confirmed": order.confirmed,
        "date_add": order.date_add,
        "date_confirmed": order.date_confirmed,
        "date_in_status": order.date_in_status,
        "delivery_method": order.delivery_method or "",
        "delivery_method_id": order.delivery_method_id,
        "delivery_price": float(order.delivery_price) if order.delivery_price else 0,
        "delivery_company": order.delivery_company or "",
        "delivery_address": order.delivery_address or "",
        "delivery_city": order.delivery_city or "",
        "delivery_postcode": order.delivery_postcode or "",
        "delivery_country": order.delivery_country or "",
        "delivery_country_code": order.delivery_country_code or "",
        "delivery_point_id": order.delivery_point_id or "",
        "delivery_point_name": order.delivery_point_name or "",
        "delivery_point_address": order.delivery_point_address or "",
        "delivery_point_postcode": order.delivery_point_postcode or "",
        "delivery_point_city": order.delivery_point_city or "",
        "invoice_fullname": order.invoice_fullname or "",
        "invoice_company": order.invoice_company or "",
        "invoice_nip": order.invoice_nip or "",
        "invoice_address": order.invoice_address or "",
        "invoice_city": order.invoice_city or "",
        "invoice_postcode": order.invoice_postcode or "",
        "invoice_country": order.invoice_country or "",
        "want_invoice": order.want_invoice or "0",
        "currency": order.currency or "PLN",
        "payment_method": order.payment_method or "",
        "payment_method_cod": order.payment_method_cod or "0",
        "payment_done": float(order.payment_done) if order.payment_done else 0,
        "user_comments": order.user_comments or "",
        "admin_comments": order.admin_comments or "",
        "courier_code": order.courier_code or "",
        "delivery_package_module": order.delivery_package_module or "",
        "delivery_package_nr": order.delivery_package_nr or "",
        "products": products_list,
    }


__all__ = ["collect_printable_orders"]