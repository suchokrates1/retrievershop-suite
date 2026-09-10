"""Korekty faktur dla nieodebranych przesylek (bez czekania na zwrot kasy)."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from ..db import get_session
from ..domain.returns import RETURN_STATUS_NOT_COLLECTED
from ..models.orders import Order, OrderStatusLog
from ..models.returns import Return
from .invoice_service import generate_correction_invoice
from .order_status import add_order_status
from .return_core import add_return_status_log
from .return_refunds import _is_cod_order


logger = logging.getLogger(__name__)

NOT_COLLECTED_CORRECTION_REASON = (
    "Nieodebranie przesylki - paczka wrocila do nadawcy"
)


def promote_unclaimed_orders_to_zwrot(
    *,
    log: Optional[logging.Logger] = None,
) -> Dict[str, int]:
    """Nieodebranie to podstatus zwrotu: status zamowienia ma byc 'zwrot'."""
    active_logger = log or logger
    stats = {"updated": 0, "skipped": 0}

    with get_session() as db:
        rows = (
            db.query(Return)
            .filter(Return.status == RETURN_STATUS_NOT_COLLECTED)
            .all()
        )
        for return_record in rows:
            latest = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == return_record.order_id)
                .order_by(OrderStatusLog.timestamp.desc(), OrderStatusLog.id.desc())
                .first()
            )
            if latest and latest.status == "zwrot":
                stats["skipped"] += 1
                continue
            add_order_status(
                db,
                return_record.order_id,
                "zwrot",
                send_email=False,
                notes="Nieodebranie to podstatus zwrotu",
            )
            stats["updated"] += 1
            active_logger.info(
                "Status zamowienia %s: %s -> zwrot (nieodebrane)",
                return_record.order_id,
                latest.status if latest else None,
            )
        db.commit()

    return stats


def process_not_collected_corrections(
    *,
    issue_correction=generate_correction_invoice,
    log: Optional[logging.Logger] = None,
) -> Dict[str, int]:
    """Wystaw korekte + mail dla zwrotow not_collected z faktura, bez korekty.

    Przy pobraniu nie czekamy na zwrot kasy - wplaty nie bylo.
    """
    active_logger = log or logger
    stats = {"processed": 0, "success": 0, "skipped": 0, "errors": 0}

    with get_session() as db:
        rows = (
            db.query(Return, Order)
            .join(Order, Order.order_id == Return.order_id)
            .filter(
                Return.status == RETURN_STATUS_NOT_COLLECTED,
                Order.wfirma_invoice_id.isnot(None),
                Order.wfirma_correction_id.is_(None),
            )
            .all()
        )
        targets = [
            (ret.id, order.order_id, _is_cod_order(order))
            for ret, order in rows
        ]

    if not targets:
        return stats

    for return_id, order_id, is_cod in targets:
        stats["processed"] += 1
        try:
            result = issue_correction(
                order_id=order_id,
                reason=NOT_COLLECTED_CORRECTION_REASON,
                return_id=None,
                include_delivery=True,
                include_refund_amount=not is_cod,
                is_unclaimed=True,
            )
            if result.get("already_exists"):
                stats["skipped"] += 1
                continue
            if not result.get("success"):
                stats["errors"] += 1
                active_logger.warning(
                    "Nie udalo sie wystawic korekty dla nieodebranego %s: %s",
                    order_id,
                    result.get("errors"),
                )
                continue

            invoice_number = result.get("invoice_number")
            note = f"Wystawiono korekte {invoice_number}"
            if is_cod:
                note = (
                    f"{note} - brak wplaty (pobranie), bez zwrotu kasy"
                )
            with get_session() as db:
                add_return_status_log(
                    db,
                    return_id,
                    RETURN_STATUS_NOT_COLLECTED,
                    note,
                )
                db.commit()
            stats["success"] += 1
            active_logger.info(
                "Korekta %s dla nieodebranego zamowienia %s",
                invoice_number,
                order_id,
            )
        except Exception as exc:
            stats["errors"] += 1
            active_logger.error(
                "Blad korekty dla nieodebranego zamowienia %s: %s",
                order_id,
                exc,
                exc_info=True,
            )

    return stats


__all__ = [
    "NOT_COLLECTED_CORRECTION_REASON",
    "process_not_collected_corrections",
    "promote_unclaimed_orders_to_zwrot",
]
