"""Orkiestracja pelnej synchronizacji zwrotow."""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..domain.returns import (
    RETURN_STATUS_PENDING,
    RETURN_STATUS_IN_TRANSIT,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_COMPLETED,
    RETURN_STATUS_CANCELLED,
    map_carrier_to_allegro as _map_carrier_to_allegro,
)
from .return_allegro import (
    check_allegro_customer_returns,
    check_and_update_return_statuses,
    send_pending_return_notifications,
)
from .return_core import expire_stale_returns
from .return_notifications import send_return_notification
from .return_stock import process_delivered_returns


logger = logging.getLogger(__name__)


def sync_returns() -> Dict[str, Any]:
    """Wykonaj pelna synchronizacje systemu zwrotow."""
    logger.info("Rozpoczynam synchronizacje zwrotow")

    results = {
        "allegro": check_allegro_customer_returns(log=logger),
        "notifications": send_pending_return_notifications(log=logger),
        "status_updates": check_and_update_return_statuses(log=logger),
        "stock_restoration": process_delivered_returns(log=logger),
        "expired": expire_stale_returns(log=logger),
    }

    logger.info("Synchronizacja zwrotow zakonczona: %s", results)
    return results


class ReturnSyncService:
    """Klasa adaptera dla kodu oczekujacego obiektu serwisu zwrotow."""
    
    def __init__(self, db_session=None):
        self._db = db_session
    
    def sync_all(self) -> Dict[str, Any]:
        """Wykonaj pelna synchronizacje zwrotow."""
        return sync_returns()
    
    def check_allegro_returns(self) -> Dict[str, int]:
        """Sprawdz zwroty w Allegro Customer Returns API."""
        return check_allegro_customer_returns(log=logger)


def create_return_sync_service() -> ReturnSyncService:
    """Fabryka do tworzenia ReturnSyncService."""
    return ReturnSyncService()


__all__ = [
    "ReturnSyncService",
    "create_return_sync_service",
    "sync_returns",
    "check_allegro_customer_returns",
    "send_pending_return_notifications",
    "check_and_update_return_statuses",
    "process_delivered_returns",
    "expire_stale_returns",
    "_map_carrier_to_allegro",
    "send_return_notification",
    "RETURN_STATUS_PENDING",
    "RETURN_STATUS_IN_TRANSIT",
    "RETURN_STATUS_DELIVERED",
    "RETURN_STATUS_COMPLETED",
    "RETURN_STATUS_CANCELLED",
]
