"""Budowanie kontekstu listy zamowien."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..db import get_session
from ..repositories.order_repository import OrderRepository
from .order_presentation import _get_status_display, _unix_to_datetime


def _request_value(args: Any, key: str, default: Any = "", *, value_type: type | None = None) -> Any:
    getter = getattr(args, "get", None)
    if not getter:
        return default
    if value_type is int:
        return getter(key, default, type=int)
    return getter(key, default)


def build_orders_list_context(args: Any) -> dict[str, Any]:
    page = _request_value(args, "page", 1, value_type=int)
    per_page = _request_value(args, "per_page", 25, value_type=int)
    search = (_request_value(args, "search", "") or "").strip()
    sort_by = _request_value(args, "sort", "date")
    sort_dir = _request_value(args, "dir", "desc")
    status_filter = _request_value(args, "status", "all")
    date_from = (_request_value(args, "date_from", "") or "").strip()
    date_to = (_request_value(args, "date_to", "") or "").strip()

    if per_page not in [10, 25, 50, 100]:
        per_page = 25

    with get_session() as db:
        repository = OrderRepository(db)
        query = repository.list_query(
            search=search,
            status_filter=status_filter,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

        total = query.count()
        orders = query.offset((page - 1) * per_page).limit(per_page).all()
        lp_map = {
            order_id: idx + 1
            for idx, order_id in enumerate(repository.chronological_order_ids(search=search))
        }

        orders_data = []
        for order in orders:
            latest_status = repository.latest_status(order.order_id)
            status_text, status_class = _get_status_display(
                latest_status.status if latest_status else "pobrano"
            )
            products = repository.order_products(order.order_id)
            active_return = repository.active_return(order.order_id)

            product_lines = [f"{product.name or 'Produkt'} x{product.quantity}" for product in products]
            return_info = None
            if active_return:
                return_info = {
                    "status": active_return.status,
                    "refund_processed": active_return.refund_processed,
                }

            is_cod = bool(order.payment_method_cod) or (
                "pobranie" in (order.payment_method or "").lower()
            )
            if is_cod:
                products_total = sum(
                    Decimal(str(product.price_brutto or 0)) * product.quantity
                    for product in products
                )
                delivery = Decimal(str(order.delivery_price or 0))
                sale_price = float(products_total + delivery)
            else:
                sale_price = float(order.payment_done) if order.payment_done else None

            orders_data.append(
                {
                    "order_id": order.order_id,
                    "lp": lp_map.get(order.order_id, 0),
                    "external_order_id": order.external_order_id,
                    "shop_order_id": order.shop_order_id,
                    "customer_name": order.customer_name,
                    "platform": order.platform,
                    "date_add": _unix_to_datetime(order.date_add),
                    "delivery_method": order.delivery_method,
                    "sale_price": sale_price,
                    "currency": order.currency,
                    "status_text": status_text,
                    "status_class": status_class,
                    "product_summary": product_lines,
                    "tracking_number": order.delivery_package_nr,
                    "return_info": return_info,
                }
            )

    total_pages = (total + per_page - 1) // per_page
    return {
        "orders": orders_data,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "total": total,
        "search": search,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "status_filter": status_filter,
        "date_from": date_from,
        "date_to": date_to,
    }


__all__ = ["build_orders_list_context"]