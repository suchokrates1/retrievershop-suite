"""Statusy zamowien ustawiane przez agenta drukowania."""

from __future__ import annotations

import logging


def set_print_error_status(
    order_id: str,
    notes: str,
    logger: logging.Logger,
) -> None:
    """Ustaw status blad_druku, logujac nieudana probe bez przerywania petli."""
    try:
        from .order_status import add_order_status
        from ..db import get_session

        with get_session() as db:
            add_order_status(db, order_id, "blad_druku", notes=notes)
    except Exception:
        logger.warning("Nie udalo sie ustawic blad_druku dla %s", order_id)


__all__ = ["set_print_error_status"]