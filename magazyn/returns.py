"""Fasada kompatybilnosci dla operacji zwrotow.

Nowa logika biznesowa znajduje sie w modulach ``magazyn.services.return_*``.
Ten plik pozostaje dla starszych importow i testow, ktore jeszcze wskazuja na
``magazyn.returns``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from .db import get_session
from .domain.returns import (
    RETURN_STATUS_CANCELLED,
    RETURN_STATUS_COMPLETED,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_IN_TRANSIT,
    RETURN_STATUS_PENDING,
    map_allegro_return_status as _map_allegro_return_status,
    map_carrier_to_allegro as _map_carrier_to_allegro,
)
from .models.orders import Order
from .models.returns import Return
from .notifications import send_messenger
from .services.return_allegro import (
    check_allegro_customer_returns,
    check_and_update_return_statuses,
    send_pending_return_notifications,
    track_return_parcel,
)
from .services.return_core import (
    add_return_status_log as _add_return_status_log,
    create_return_from_order,
    expire_stale_returns,
    get_return_by_order_id,
    get_returns_list,
    mark_return_as_delivered,
)
from .services.return_notifications import (
    get_order_products_summary as _service_get_order_products_summary,
    send_return_notification as _service_send_return_notification,
)
from .services.return_refunds import (
    check_refund_eligibility,
    process_refund,
)
from .services.return_stock import (
    process_delivered_returns as _process_delivered_returns_service,
    restore_stock_for_return as _restore_stock_for_return_service,
)
from .services.return_sync import sync_returns

logger = logging.getLogger(__name__)


def _get_order_products_summary(order: Order) -> List[Dict[str, Any]]:
    """Zachowaj stary prywatny helper jako delegacje do serwisu."""
    return _service_get_order_products_summary(order)


def _send_return_notification(return_record: Return) -> bool:
    """Zachowaj stary prywatny helper jako delegacje do serwisu."""
    return _service_send_return_notification(
        return_record,
        send_message=send_messenger,
        log=logger,
    )


def restore_stock_for_return(return_id: int) -> Tuple[bool, str]:
    """Przywroc stan magazynowy dla zwrotu przez serwis stock."""
    return _restore_stock_for_return_service(
        return_id,
        send_message=send_messenger,
        log=logger,
    )


def process_delivered_returns() -> Dict[str, int]:
    """Przetworz dostarczone zwroty przez serwis stock."""
    return _process_delivered_returns_service(
        restore_stock=restore_stock_for_return,
        log=logger,
    )


__all__ = [
    "RETURN_STATUS_PENDING",
    "RETURN_STATUS_IN_TRANSIT",
    "RETURN_STATUS_DELIVERED",
    "RETURN_STATUS_COMPLETED",
    "RETURN_STATUS_CANCELLED",
    "_map_allegro_return_status",
    "_map_carrier_to_allegro",
    "_add_return_status_log",
    "_get_order_products_summary",
    "_send_return_notification",
    "check_allegro_customer_returns",
    "check_and_update_return_statuses",
    "check_refund_eligibility",
    "create_return_from_order",
    "expire_stale_returns",
    "get_return_by_order_id",
    "get_returns_list",
    "get_session",
    "mark_return_as_delivered",
    "process_delivered_returns",
    "process_refund",
    "restore_stock_for_return",
    "send_messenger",
    "send_pending_return_notifications",
    "sync_returns",
    "track_return_parcel",
]