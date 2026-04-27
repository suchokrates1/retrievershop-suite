"""Podstawowe operacje na zwrotach zapisanych w bazie."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import desc

from ..db import get_session
from ..domain.returns import (
    RETURN_STATUS_CANCELLED,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_PENDING,
)
from ..models.orders import Order
from ..models.returns import Return, ReturnStatusLog
from .return_notifications import get_order_products_summary

logger = logging.getLogger(__name__)


def add_return_status_log(db, return_id: int, status: str, notes: str = None) -> None:
    """Dodaj wpis do historii statusow zwrotu."""
    db.add(ReturnStatusLog(return_id=return_id, status=status, notes=notes))


def create_return_from_order(
    order: Order,
    tracking_number: str = None,
    allegro_return_id: str = None,
    *,
    log: Optional[logging.Logger] = None,
) -> Optional[Return]:
    """Utworz rekord zwrotu na podstawie zamowienia."""
    active_logger = log or logger

    with get_session() as db:
        existing = db.query(Return).filter(Return.order_id == order.order_id).first()
        if existing:
            active_logger.info(
                "Zwrot dla zamowienia %s juz istnieje (ID: %s)",
                order.order_id,
                existing.id,
            )
            return existing

        items = get_order_products_summary(order)
        return_record = Return(
            order_id=order.order_id,
            status=RETURN_STATUS_PENDING,
            customer_name=order.customer_name,
            items_json=json.dumps(items, ensure_ascii=False),
            return_tracking_number=tracking_number,
            allegro_return_id=allegro_return_id,
        )
        db.add(return_record)
        db.flush()

        add_return_status_log(
            db,
            return_record.id,
            RETURN_STATUS_PENDING,
            f"Utworzono zwrot dla zamowienia {order.order_id}",
        )

        db.commit()
        active_logger.info("Utworzono zwrot #%s dla zamowienia %s", return_record.id, order.order_id)
        return return_record


def expire_stale_returns(*, log: Optional[logging.Logger] = None) -> Dict[str, int]:
    """Zamknij zwroty bez nadanej paczki po 16 dniach od zgloszenia."""
    from .order_status import add_order_status

    active_logger = log or logger
    stats = {"expired": 0, "errors": 0}
    cutoff = datetime.utcnow() - timedelta(days=16)

    with get_session() as db:
        stale_returns = db.query(Return).filter(
            Return.status == RETURN_STATUS_PENDING,
            Return.return_tracking_number.is_(None),
            Return.created_at < cutoff,
        ).all()

        for return_record in stale_returns:
            try:
                return_record.status = RETURN_STATUS_CANCELLED
                add_return_status_log(
                    db,
                    return_record.id,
                    RETURN_STATUS_CANCELLED,
                    "Zwrot wygasl - brak nadania przesylki w ciagu 16 dni od zgloszenia",
                )
                add_order_status(
                    db,
                    return_record.order_id,
                    "dostarczono",
                    allow_backwards=True,
                    notes="Zwrot wygasl (brak nadania w terminie) - przywrocono status zakonczonego zamowienia",
                )
                stats["expired"] += 1
                active_logger.info(
                    "Zwrot #%s (zamowienie %s) wygasl - brak nadania w 16 dni",
                    return_record.id,
                    return_record.order_id,
                )
            except Exception as exc:
                active_logger.error("Blad wygaszania zwrotu #%s: %s", return_record.id, exc)
                stats["errors"] += 1
        db.commit()

    return stats


def get_return_by_order_id(order_id: str) -> Optional[Return]:
    """Pobierz zwrot po ID zamowienia."""
    with get_session() as db:
        return db.query(Return).filter(Return.order_id == order_id).first()


def get_returns_list(status: str = None, limit: int = 50) -> List[Return]:
    """Pobierz liste zwrotow z opcjonalnym filtrem statusu."""
    with get_session() as db:
        query = db.query(Return)
        if status:
            query = query.filter(Return.status == status)
        return query.order_by(desc(Return.created_at)).limit(limit).all()


def mark_return_as_delivered(
    return_id: int,
    *,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Recznie oznacz zwrot jako dostarczony."""
    active_logger = log or logger

    with get_session() as db:
        return_record = db.query(Return).filter(Return.id == return_id).first()
        if not return_record:
            return False

        if return_record.status == RETURN_STATUS_DELIVERED:
            return True

        return_record.status = RETURN_STATUS_DELIVERED
        add_return_status_log(
            db,
            return_record.id,
            RETURN_STATUS_DELIVERED,
            "Reczne oznaczenie jako dostarczone",
        )
        db.commit()

        active_logger.info("Zwrot #%s oznaczony jako dostarczony", return_id)
        return True


__all__ = [
    "add_return_status_log",
    "create_return_from_order",
    "expire_stale_returns",
    "get_return_by_order_id",
    "get_returns_list",
    "mark_return_as_delivered",
]