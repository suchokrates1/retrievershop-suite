"""Helpery zamowien uzywane przez API statystyk."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from ..models import Order, OrderProduct
from .stats_support import StatsFilters, to_ts


def is_cod(order: Order) -> bool:
    method = (order.payment_method or "").lower()
    return bool(order.payment_method_cod) or ("pobranie" in method)


def order_products_map(db: Any, order_ids: list[str]) -> dict[str, dict[str, Decimal | int]]:
    if not order_ids:
        return {}

    rows = (
        db.query(
            OrderProduct.order_id,
            func.sum(OrderProduct.quantity).label("qty"),
            func.sum(OrderProduct.price_brutto * OrderProduct.quantity).label("gross"),
        )
        .filter(OrderProduct.order_id.in_(order_ids))
        .group_by(OrderProduct.order_id)
        .all()
    )
    return {
        row.order_id: {
            "qty": int(row.qty or 0),
            "gross": Decimal(str(row.gross or 0)),
        }
        for row in rows
    }


def order_revenue(order: Order, products_map: dict[str, dict[str, Decimal | int]]) -> Decimal:
    order_products = products_map.get(order.order_id, {"gross": Decimal("0")})
    gross = Decimal(str(order_products.get("gross", Decimal("0"))))
    if is_cod(order):
        return gross + Decimal(str(order.delivery_price or 0))
    return Decimal(str(order.payment_done or 0))


def filter_orders_by_payment(orders: list[Order], payment_type: str) -> list[Order]:
    if payment_type == "all":
        return orders
    if payment_type == "cod":
        return [order for order in orders if is_cod(order)]
    return [order for order in orders if not is_cod(order)]


def fetch_orders(db: Any, filters: StatsFilters, start_ts: int, end_ts: int) -> list[Order]:
    query = db.query(Order).filter(Order.date_add >= start_ts, Order.date_add < end_ts)
    if filters.platform != "all":
        query = query.filter(Order.platform == filters.platform)
    orders = query.all()
    return filter_orders_by_payment(orders, filters.payment_type)


def bucket_key(ts: int, granularity: str) -> str:
    dt = datetime.fromtimestamp(ts)
    if granularity == "week":
        week_start = dt - timedelta(days=dt.weekday())
        return week_start.strftime("%Y-%m-%d")
    if granularity == "month":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


def period_offsets(filters: StatsFilters) -> tuple[int, int, int, int]:
    current_start = to_ts(filters.date_from)
    current_end = to_ts(filters.date_to)
    period_len = filters.date_to - filters.date_from
    prev_start = to_ts(filters.date_from - period_len)
    prev_end = current_start
    return current_start, current_end, prev_start, prev_end


__all__ = [
    "bucket_key",
    "fetch_orders",
    "filter_orders_by_payment",
    "is_cod",
    "order_products_map",
    "order_revenue",
    "period_offsets",
]