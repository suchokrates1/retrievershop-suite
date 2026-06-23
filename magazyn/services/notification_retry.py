"""Ponawianie nieudanych powiadomień do kupujących Allegro."""

from __future__ import annotations

import logging
import time

from sqlalchemy import desc

from ..db import get_session
from ..models.orders import Order, OrderStatusLog
from ..status_config import STATUS_EMAIL_MAP, STATUS_HIERARCHY
from .email_service import (
    send_delivery_confirmation,
    send_order_confirmation,
    send_shipment_notification,
)
from .invoice_service import generate_and_send_invoice
from .notification_delivery import is_allegro_proxy_email, was_notification_sent

logger = logging.getLogger(__name__)

_STATUS_PRIORITY = STATUS_HIERARCHY


def _order_reached_status(order_id: str, target_status: str, db) -> bool:
    target_prio = _STATUS_PRIORITY.get(target_status, -1)
    if target_prio < 0:
        return False
    logs = (
        db.query(OrderStatusLog)
        .filter(OrderStatusLog.order_id == order_id)
        .order_by(desc(OrderStatusLog.timestamp))
        .all()
    )
    for log in logs:
        prio = _STATUS_PRIORITY.get(log.status, -1)
        if prio == 999:
            continue
        if prio >= target_prio:
            return True
    return False


def retry_pending_allegro_notifications() -> dict:
    """
    Ponów powiadomienia dla zamówień Allegro z @allegromail.pl,
    które nie zostały oznaczone jako dostarczone.
    """
    stats = {"checked": 0, "retried": 0, "success": 0, "errors": 0}
    cutoff = int(time.time()) - 14 * 24 * 3600

    with get_session() as db:
        orders = (
            db.query(Order)
            .filter(
                Order.order_id.like("allegro_%"),
                Order.date_add >= cutoff,
                Order.email.isnot(None),
            )
            .all()
        )

        for order in orders:
            if not is_allegro_proxy_email(order.email):
                continue
            stats["checked"] += 1

            for status, email_type in STATUS_EMAIL_MAP.items():
                if was_notification_sent(order, email_type):
                    continue
                if not _order_reached_status(order.order_id, status, db):
                    continue
                if email_type == "shipment" and not order.delivery_package_nr:
                    continue

                stats["retried"] += 1
                try:
                    delivery = None
                    if email_type == "confirmation":
                        delivery = send_order_confirmation(order)
                    elif email_type == "shipment":
                        delivery = send_shipment_notification(order)
                    elif email_type == "delivery":
                        delivery = send_delivery_confirmation(order)

                    if delivery and delivery.success:
                        from .notification_delivery import _mark_email_sent

                        _mark_email_sent(db, order, email_type, delivery)
                        stats["success"] += 1
                        db.commit()
                    else:
                        stats["errors"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    logger.error(
                        "Retry powiadomienia %s dla %s: %s",
                        email_type,
                        order.order_id,
                        exc,
                    )

            if (
                not was_notification_sent(order, "invoice")
                and order.delivery_package_nr
                and not order.wfirma_invoice_id
            ):
                stats["retried"] += 1
                try:
                    result = generate_and_send_invoice(order.order_id)
                    if result.get("success"):
                        stats["success"] += 1
                    else:
                        stats["errors"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    logger.error(
                        "Retry faktury dla %s: %s",
                        order.order_id,
                        exc,
                    )

        db.commit()

    if stats["retried"] > 0:
        logger.info(
            "Retry powiadomień Allegro: checked=%s retried=%s success=%s errors=%s",
            stats["checked"],
            stats["retried"],
            stats["success"],
            stats["errors"],
        )
    return stats


__all__ = ["retry_pending_allegro_notifications"]
