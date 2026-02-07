"""
Serwis synchronizacji zwrotow - wrapper nad returns.py.

UWAGA: Glowna logika zwrotow znajduje sie w magazyn/returns.py.
Ten modul pelni role adaptera dla kompatybilnosci z services/__init__.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..returns import (
    sync_returns,
    check_baselinker_returns,
    send_pending_return_notifications,
    _map_carrier_to_allegro,
    _send_return_notification as send_return_notification,
    BASELINKER_RETURN_STATUS_ID,
    RETURN_STATUS_PENDING,
    RETURN_STATUS_IN_TRANSIT,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_COMPLETED,
    RETURN_STATUS_CANCELLED,
)


logger = logging.getLogger(__name__)


class ReturnSyncService:
    """
    Adapter klasy serwisowej nad returns.py.
    
    Deleguje wywolania do funkcji z returns.py.
    Preferuj bezposrednie uzycie funkcji z returns.py w nowym kodzie.
    """
    
    def __init__(self, db_session=None):
        self._db = db_session
    
    def sync_all(self) -> Dict[str, Any]:
        """Wykonaj pelna synchronizacje zwrotow (delegacja do returns.sync_returns)."""
        return sync_returns()
    
    def check_baselinker_returns(self) -> Dict[str, int]:
        """Sprawdz zwroty w BaseLinker (delegacja do returns.check_baselinker_returns)."""
        return check_baselinker_returns()


def create_return_sync_service() -> ReturnSyncService:
    """Fabryka do tworzenia ReturnSyncService."""
    return ReturnSyncService()
