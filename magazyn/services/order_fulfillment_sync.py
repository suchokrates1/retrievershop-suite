"""Synchronizacja statusow fulfillment zamowien Allegro."""

from __future__ import annotations

import logging

from sqlalchemy import and_, desc, func

from ..allegro_api.orders import (
    ALLEGRO_FULFILLMENT_MAP,
    fetch_allegro_order_detail,
    get_allegro_internal_status,
    parse_allegro_order_to_data,
)
from ..db import get_session
from ..models.orders import Order, OrderStatusLog
from .order_status import add_order_status

logger = logging.getLogger(__name__)

ACTIVE_FULFILLMENT_STATUSES = [
    "wydrukowano",
    "spakowano",
    "wyslano",
    "w_transporcie",
    "w_punkcie",
]


def is_http_status(exc: Exception, status_code: int) -> bool:
    """Sprawdz kod odpowiedzi HTTP przenoszony przez wyjatek klienta API."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == status_code


def sync_allegro_fulfillment(app=None, *, log: logging.Logger | None = None) -> dict[str, int]:
    """Synchronizuj statusy realizacji zamowien z Allegro API."""
    active_logger = log or logger
    stats = {"checked": 0, "updated": 0, "errors": 0, "skipped": 0, "missing": 0}

    try:
        with get_session() as db:
            latest_status_subq = (
                db.query(
                    OrderStatusLog.order_id,
                    func.max(OrderStatusLog.timestamp).label("max_ts"),
                )
                .group_by(OrderStatusLog.order_id)
                .subquery()
            )

            orders = (
                db.query(Order)
                .join(OrderStatusLog, OrderStatusLog.order_id == Order.order_id)
                .join(
                    latest_status_subq,
                    and_(
                        OrderStatusLog.order_id == latest_status_subq.c.order_id,
                        OrderStatusLog.timestamp == latest_status_subq.c.max_ts,
                    ),
                )
                .filter(
                    OrderStatusLog.status.in_(ACTIVE_FULFILLMENT_STATUSES),
                    Order.external_order_id.isnot(None),
                    Order.external_order_id != "",
                )
                .distinct()
                .all()
            )

            active_logger.info("Allegro fulfillment sync: %s zamowien do sprawdzenia", len(orders))

            for order in orders:
                try:
                    result = _sync_order_fulfillment(db, order, active_logger)
                    if result == "updated":
                        stats["updated"] += 1
                    elif result == "skipped":
                        stats["skipped"] += 1
                    stats["checked"] += 1
                except Exception as exc:
                    if is_http_status(exc, 404):
                        active_logger.debug(
                            "Allegro fulfillment: checkout-form %s nie istnieje juz w API, pomijam zamowienie %s",
                            order.external_order_id,
                            order.order_id,
                        )
                        stats["missing"] += 1
                        continue

                    active_logger.warning("Blad sprawdzania fulfillment dla %s: %s", order.order_id, exc)
                    stats["errors"] += 1

            db.commit()
    except Exception as exc:
        active_logger.error("Krytyczny blad sync fulfillment: %s", exc, exc_info=True)
        stats["errors"] += 1

    return stats


def _sync_order_fulfillment(db, order: Order, log: logging.Logger) -> str:
    detail = fetch_allegro_order_detail(order.external_order_id)

    parsed = parse_allegro_order_to_data(detail)
    derived_status = get_allegro_internal_status(parsed)

    fulfillment = detail.get("fulfillment", {}) or {}
    fulfillment_status = fulfillment.get("status", "")

    if not fulfillment_status:
        return "skipped"

    new_status = ALLEGRO_FULFILLMENT_MAP.get(fulfillment_status)
    if not new_status:
        if derived_status == "anulowano":
            new_status = "anulowano"
        else:
            return "skipped"

    if derived_status == "anulowano":
        new_status = "anulowano"

    current_log = (
        db.query(OrderStatusLog)
        .filter(OrderStatusLog.order_id == order.order_id)
        .order_by(desc(OrderStatusLog.timestamp))
        .first()
    )
    current_status = current_log.status if current_log else None

    if current_status == new_status:
        return "unchanged"

    log.info(
        "Allegro fulfillment: %s %s -> %s (fulfillment: %s)",
        order.order_id,
        current_status,
        new_status,
        fulfillment_status,
    )
    add_order_status(
        db,
        order.order_id,
        new_status,
        notes=f"Allegro fulfillment sync: {fulfillment_status}",
    )
    return "updated"


__all__ = [
    "ACTIVE_FULFILLMENT_STATUSES",
    "is_http_status",
    "sync_allegro_fulfillment",
]