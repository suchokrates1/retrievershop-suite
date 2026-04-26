"""Serwis statusów zamówień."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Optional

from sqlalchemy import desc

from ..models import Order, OrderStatusLog
from ..status_config import STATUS_EMAIL_MAP, STATUS_HIERARCHY


logger = logging.getLogger(__name__)


def dispatch_status_email(db, order_id: str, status: str) -> None:
    """Wyślij email do klienta przy zmianie statusu zamówienia."""
    email_type = STATUS_EMAIL_MAP.get(status)
    if not email_type:
        logger.debug("Email dispatch: brak mapowania dla statusu '%s'", status)
        return

    from .invoice_service import _mark_email_sent, _was_email_sent

    db.flush()

    order = db.query(Order).filter(Order.order_id == order_id).first()
    if not order or not order.email:
        logger.warning(
            "Email dispatch: brak zamowienia lub adresu email dla %s", order_id
        )
        return

    if _was_email_sent(order, email_type):
        logger.debug("Email '%s' juz wyslany dla %s - pomijam", email_type, order_id)
        return

    logger.info(
        "Wysylam email '%s' dla zamowienia %s na %s",
        email_type,
        order_id,
        order.email,
    )

    try:
        from .email_service import (
            send_delivery_confirmation,
            send_invoice_correction,
            send_order_confirmation,
            send_shipment_notification,
        )

        sent = False
        if email_type == "confirmation":
            sent = send_order_confirmation(order)
        elif email_type == "shipment":
            sent = send_shipment_notification(order)
        elif email_type == "delivery":
            sent = send_delivery_confirmation(order)
        elif email_type == "correction":
            sent = send_invoice_correction(order)

        if sent:
            _mark_email_sent(db, order, email_type)
            logger.info("Email '%s' wyslany dla zamowienia %s", email_type, order_id)
        else:
            logger.warning(
                "Email '%s' NIE wyslany dla zamowienia %s (send zwrocilo False)",
                email_type,
                order_id,
            )
    except Exception as exc:
        logger.error(
            "Blad wysylki emaila '%s' dla zamowienia %s: %s",
            email_type,
            order_id,
            exc,
            exc_info=True,
        )


def add_order_status(
    db,
    order_id: str,
    status: str,
    skip_if_same: bool = True,
    allow_backwards: bool = False,
    send_email: bool = True,
    *,
    dispatch_email: Callable[[object, str, str], None] = dispatch_status_email,
    **kwargs,
) -> Optional[OrderStatusLog]:
    """Dodaj wpis historii statusu i opcjonalnie wyślij mail statusowy."""
    order = db.query(Order).filter(Order.order_id == order_id).first()

    tracking_number = kwargs.get("tracking_number")
    courier_code = kwargs.get("courier_code")

    if order is not None:
        if tracking_number:
            order.delivery_package_nr = tracking_number
        if courier_code:
            order.courier_code = courier_code

    last_status = (
        db.query(OrderStatusLog)
        .filter(OrderStatusLog.order_id == order_id)
        .order_by(desc(OrderStatusLog.timestamp))
        .first()
    )

    if skip_if_same and last_status and last_status.status == status:
        return None

    if not allow_backwards and last_status:
        last_priority = STATUS_HIERARCHY.get(last_status.status, -1)
        new_priority = STATUS_HIERARCHY.get(status, -1)

        if (
            new_priority != 999
            and last_priority != 999
            and last_priority != -1
            and new_priority < last_priority
        ):
            logger.warning(
                "Pominięto cofnięcie statusu zamówienia %s: %s (priorytet %s) -> %s (priorytet %s)",
                order_id,
                last_status.status,
                last_priority,
                status,
                new_priority,
            )
            return None

    log = OrderStatusLog(
        order_id=order_id,
        status=status,
        tracking_number=tracking_number,
        courier_code=courier_code,
        notes=kwargs.get("notes"),
    )
    db.add(log)

    if send_email:
        dispatch_email(db, order_id, status)

    return log


__all__ = ["add_order_status", "dispatch_status_email"]