"""Cofnięcie stanów zdjętych przy druku, a nie przy spakowaniu albo wysyłce.

Sprzedaż zostaje tylko dla zamówień, które doszły co najmniej do spakowania,
i tylko w liczbie sztuk z zamówienia. Nadmiar z drugiego wydruku wraca na stan.
Zamówienie wyłącznie wydrukowane nie ma jeszcze sprzedaży — stan wraca w całości,
a zejdzie przy spakowaniu.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import desc

from ..db import get_session
from ..domain.inventory import FULFILLMENT_STATUSES
from ..models.orders import OrderProduct, OrderStatusLog
from ..models.products import ProductSize, Sale

logger = logging.getLogger(__name__)

_SKIP_STATUSES = frozenset({"zwrot", "anulowano", "nieodebrano"})
SizeKey = Tuple[int, str]


def correct_print_stock_deductions() -> List[dict]:
    """Zwraca listę cofniętych wierszy sprzedaży. Nic nie robi, gdy nie ma nadmiaru."""
    actions: List[dict] = []
    woo_pushes: List[tuple] = []
    with get_session() as db:
        order_ids = [
            row[0]
            for row in db.query(Sale.order_id).filter(Sale.order_id.isnot(None)).distinct()
        ]
        latest = _latest_statuses(db, order_ids)
        blocked = _orders_with_return(db, order_ids)
        for order_id in order_ids:
            status = latest.get(order_id)
            if order_id in blocked or status in _SKIP_STATUSES:
                continue
            actions.extend(_correct_order(db, order_id, status, woo_pushes))
    _push_woo(woo_pushes)
    return actions


def _orders_with_return(db, order_ids: List[str]) -> set:
    if not order_ids:
        return set()
    rows = (
        db.query(OrderStatusLog.order_id)
        .filter(
            OrderStatusLog.order_id.in_(order_ids),
            OrderStatusLog.status.in_(_SKIP_STATUSES),
        )
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def _latest_statuses(db, order_ids: List[str]) -> Dict[str, str]:
    if not order_ids:
        return {}
    logs = (
        db.query(OrderStatusLog)
        .filter(OrderStatusLog.order_id.in_(order_ids))
        .order_by(desc(OrderStatusLog.timestamp), desc(OrderStatusLog.id))
        .all()
    )
    found: Dict[str, str] = {}
    for log in logs:
        if log.order_id not in found:
            found[log.order_id] = log.status
    return found


def _correct_order(db, order_id: str, status: Optional[str], woo_pushes: list) -> List[dict]:
    products = db.query(OrderProduct).filter(OrderProduct.order_id == order_id).all()
    fulfilled = status in FULFILLMENT_STATUSES
    expected = _expected_quantities(db, products) if fulfilled else {}
    if fulfilled and not expected:
        logger.warning(
            "Pomijam %s (status %s): brak dopasowania pozycji do rozmiaru, nic nie cofam",
            order_id,
            status,
        )
        return []
    sales = (
        db.query(Sale)
        .filter(Sale.order_id == order_id)
        .order_by(Sale.id.asc())
        .all()
    )
    keep_left = dict(expected)
    actions: List[dict] = []
    for sale in sales:
        key = (sale.product_id, sale.size or "")
        left = keep_left.get(key, 0)
        qty = sale.quantity or 0
        if left > 0 and qty <= left and (sale.quantity_returned or 0) == 0:
            keep_left[key] = left - qty
            continue
        if (sale.quantity_returned or 0) > 0:
            logger.warning(
                "Pomijam sale %s zamówienia %s — ma już zwrot quantity_returned=%s",
                sale.id,
                order_id,
                sale.quantity_returned,
            )
            continue
        if not _restore_sale(db, sale, woo_pushes):
            continue
        actions.append(
            {
                "order_id": order_id,
                "sale_id": sale.id,
                "product_id": sale.product_id,
                "size": sale.size,
                "quantity": qty,
                "status": status,
            }
        )
        logger.info(
            "Cofnieto sprzedaz %s z druku: order=%s qty=%s size=%s status=%s",
            sale.id,
            order_id,
            qty,
            sale.size,
            status,
        )
    return actions


def _expected_quantities(db, products: List[OrderProduct]) -> Dict[SizeKey, int]:
    expected: Dict[SizeKey, int] = {}
    for product in products:
        size_row = None
        if product.product_size_id:
            size_row = db.query(ProductSize).filter(ProductSize.id == product.product_size_id).first()
        if size_row is None and product.ean:
            size_row = db.query(ProductSize).filter(ProductSize.barcode == product.ean).first()
        if size_row is None:
            continue
        key = (size_row.product_id, size_row.size or "")
        expected[key] = expected.get(key, 0) + int(product.quantity or 0)
    return expected


def _restore_sale(db, sale: Sale, woo_pushes: list) -> bool:
    size_row = (
        db.query(ProductSize)
        .filter_by(product_id=sale.product_id, size=sale.size)
        .first()
    )
    qty = sale.quantity or 0
    if size_row is not None and qty > 0:
        size_row.quantity = (size_row.quantity or 0) + qty
        size_row.stock_value = Decimal(str(size_row.stock_value or 0)) + Decimal(
            str(sale.purchase_cost or 0)
        )
        woo_pushes.append((size_row.id, size_row.woo_variation_id, size_row.quantity))
    db.delete(sale)
    return True


def _push_woo(woo_pushes: list) -> None:
    if not woo_pushes:
        return
    from .woo_stock_reconcile import maybe_push_woo_stock

    for size_id, woo_vid, quantity in woo_pushes:
        if size_id and woo_vid:
            maybe_push_woo_stock(size_id, quantity=quantity)
