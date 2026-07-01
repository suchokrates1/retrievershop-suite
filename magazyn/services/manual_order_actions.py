"""Akcje specyficzne dla zamowien recznych (OLX, sklep, inne)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc

from ..domain.returns import map_carrier_to_allegro
from ..models.orders import Order, OrderStatusLog
from .order_status import add_order_status
from .print_agent_storage import PrintAgentStorage

_logger = logging.getLogger(__name__)
_print_storage = PrintAgentStorage(
    logger=_logger,
    now=lambda: datetime.now(timezone.utc),
    handle_readonly_error=lambda _operation, _exc: False,
)


def is_manual_order(order: Order | str) -> bool:
    order_id = order if isinstance(order, str) else order.order_id
    return str(order_id).startswith("manual_")


def resolve_manual_courier_code(delivery_method: Optional[str]) -> Optional[str]:
    if not delivery_method:
        return None
    return map_carrier_to_allegro(delivery_method)


def _mark_manual_order_printed(order_id: str, *, tracking_number: str, courier_code: Optional[str]) -> None:
    _print_storage.upsert_printed_order_record(
        order_id,
        {
            "courier_code": courier_code,
            "delivery_package_nr": tracking_number,
            "manual_shipment": True,
            "skip_print": True,
        },
    )


def _refresh_manual_order_profit(db, order: Order) -> None:
    from ..domain.financial import FinancialCalculator
    from ..settings_store import settings_store

    FinancialCalculator(db, settings_store).refresh_order_profit_cache(
        order,
        trace_label="manual-order",
    )


def _current_status(db, order_id: str) -> Optional[str]:
    latest = (
        db.query(OrderStatusLog)
        .filter(OrderStatusLog.order_id == order_id)
        .order_by(desc(OrderStatusLog.timestamp), desc(OrderStatusLog.id))
        .first()
    )
    return latest.status if latest else None


def apply_manual_tracking(
    db,
    order: Order,
    tracking_number: str,
    *,
    courier_code: Optional[str] = None,
    notes: Optional[str] = None,
    advance_status: bool = True,
) -> None:
    """Przypisz numer przesylki do zamowienia recznego i oznacz jako wydrukowane."""
    tracking_number = tracking_number.strip()
    if not tracking_number:
        raise ValueError("Brak numeru przesylki")

    resolved_courier = courier_code or resolve_manual_courier_code(order.delivery_method)
    order.delivery_package_nr = tracking_number
    if resolved_courier:
        order.courier_code = resolved_courier

    db.flush()
    should_advance = advance_status and _current_status(db, order.order_id) in {
        None,
        "pobrano",
        "blad_druku",
    }
    if should_advance:
        add_order_status(
            db,
            order.order_id,
            "wydrukowano",
            courier_code=resolved_courier,
            tracking_number=tracking_number,
            notes=notes or "Reczna przesylka - numer dodany",
            send_email=False,
        )

    _mark_manual_order_printed(
        order.order_id,
        tracking_number=tracking_number,
        courier_code=resolved_courier,
    )
    _refresh_manual_order_profit(db, order)


def finalize_manual_order_creation(db, order: Order, order_data: dict[str, Any]) -> None:
    """Ustaw poczatkowy status zamowienia recznego po utworzeniu."""
    platform = order_data.get("platform", "olx")
    tracking_number = (order_data.get("delivery_package_nr") or "").strip()

    if tracking_number:
        apply_manual_tracking(
            db,
            order,
            tracking_number,
            notes=f"Zamowienie reczne ({platform}) - numer przesylki podany przy tworzeniu",
            advance_status=True,
        )
        return

    add_order_status(
        db,
        order.order_id,
        "pobrano",
        notes=f"Zamowienie reczne ({platform})",
        send_email=False,
    )
    _refresh_manual_order_profit(db, order)


__all__ = [
    "apply_manual_tracking",
    "finalize_manual_order_creation",
    "is_manual_order",
    "resolve_manual_courier_code",
]
