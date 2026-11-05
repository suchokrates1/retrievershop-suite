"""Statusy zamowien ustawiane przez agenta drukowania."""

from __future__ import annotations

import logging


def set_print_error_status(
    order_id: str,
    notes: str,
    logger: logging.Logger,
) -> None:
    """Ustaw status blad_druku, logujac nieudana probe bez przerywania petli.

    Gdy status już jest ``blad_druku``, podmienia notatkę. Inaczej kolejna
    próba z konkretnym błędem Allegro zostaje przy pierwszym, ogólnym wpisie.
    """
    try:
        from sqlalchemy import desc

        from ..db import get_session
        from ..models.orders import OrderStatusLog
        from .order_status import add_order_status

        with get_session() as db:
            last_status = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order_id)
                .order_by(desc(OrderStatusLog.timestamp), desc(OrderStatusLog.id))
                .first()
            )
            if last_status is not None and last_status.status == "blad_druku":
                if (last_status.notes or "") != notes:
                    last_status.notes = notes
                return
            add_order_status(db, order_id, "blad_druku", notes=notes)
    except Exception:
        logger.warning("Nie udalo sie ustawic blad_druku dla %s", order_id)


__all__ = ["set_print_error_status"]