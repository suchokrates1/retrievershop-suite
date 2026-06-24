"""Atrybucja realnego zysku do ofert/kampanii Ads Panel."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from magazyn.models.orders import Order, OrderProduct

WARSAW = ZoneInfo("Europe/Warsaw")


def _line_revenue(product: OrderProduct) -> Decimal:
    return Decimal(str(product.price_brutto or 0)) * int(product.quantity or 0)


def _period_bounds(period_start: date, period_end: date) -> tuple[int, int]:
    start_ts = int(datetime.combine(period_start, time.min, tzinfo=WARSAW).timestamp())
    end_ts = int(
        datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=WARSAW).timestamp()
    )
    return start_ts, end_ts


def compute_profit_by_offer(
    db,
    *,
    period_start: date,
    period_end: date,
    offer_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Zwraca atrybuowany zysk i przychód per offer_id (proporcjonalnie do linii zamówienia)."""
    normalized = {str(offer_id) for offer_id in offer_ids if offer_id}
    empty = {"real_profit": Decimal("0"), "real_revenue": Decimal("0"), "orders": 0}
    if not normalized:
        return {}

    start_ts, end_ts = _period_bounds(period_start, period_end)
    matching_rows = (
        db.query(OrderProduct.order_id)
        .join(Order, Order.order_id == OrderProduct.order_id)
        .filter(
            Order.date_add >= start_ts,
            Order.date_add < end_ts,
            Order.platform == "allegro",
            OrderProduct.auction_id.in_(normalized),
        )
        .distinct()
        .all()
    )
    order_ids = [row.order_id for row in matching_rows]
    if not order_ids:
        return {offer_id: dict(empty) for offer_id in normalized}

    orders = {
        order.order_id: order
        for order in db.query(Order).filter(Order.order_id.in_(order_ids)).all()
    }
    products_by_order: dict[str, list[OrderProduct]] = defaultdict(list)
    for product in db.query(OrderProduct).filter(OrderProduct.order_id.in_(order_ids)).all():
        products_by_order[product.order_id].append(product)

    result: dict[str, dict[str, Any]] = {
        offer_id: {"real_profit": Decimal("0"), "real_revenue": Decimal("0"), "orders": set()}
        for offer_id in normalized
    }

    for order_id, products in products_by_order.items():
        order = orders.get(order_id)
        if not order or order.real_profit_amount is None:
            continue

        order_profit = Decimal(str(order.real_profit_amount))
        total_revenue = sum(_line_revenue(product) for product in products)
        if total_revenue <= 0:
            continue

        matched = [
            product
            for product in products
            if product.auction_id and str(product.auction_id) in normalized
        ]
        matched_revenue = sum(_line_revenue(product) for product in matched)
        if matched_revenue <= 0:
            continue

        attributed_profit = order_profit * (matched_revenue / total_revenue)
        for product in matched:
            offer_id = str(product.auction_id)
            line_revenue = _line_revenue(product)
            share = line_revenue / matched_revenue
            bucket = result[offer_id]
            bucket["real_profit"] += attributed_profit * share
            bucket["real_revenue"] += line_revenue
            bucket["orders"].add(order_id)

    for offer_id, bucket in result.items():
        bucket["orders"] = len(bucket["orders"])

    return result


def _ratio(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator / denominator), 2)


def summarize_offer_profit(offer_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    real_profit = sum(
        Decimal(str(row.get("real_profit") or 0)) for row in offer_rows.values()
    )
    real_revenue = sum(
        Decimal(str(row.get("real_revenue") or 0)) for row in offer_rows.values()
    )
    orders = sum(int(row.get("orders") or 0) for row in offer_rows.values())
    return {
        "real_profit": real_profit,
        "real_revenue": real_revenue,
        "orders_matched": orders,
    }


__all__ = ["compute_profit_by_offer", "summarize_offer_profit", "_ratio"]
