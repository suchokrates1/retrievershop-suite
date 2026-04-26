"""Automatyczna aktualizacja statusow przesylek przez Allegro Tracking API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Tuple

from sqlalchemy import desc

from ..allegro_api.fulfillment import update_fulfillment_status
from ..allegro_api.tracking import fetch_parcel_tracking
from ..db import get_session
from ..models import Order, OrderStatusLog
from ..settings_store import settings_store
from ..status_config import ALLEGRO_TRACKING_MAP
from .order_status import add_order_status


TERMINAL_TRACKING_STATUSES = {
    "dostarczono",
    "zwrot",
    "anulowano",
    "problem_z_dostawa",
}


class PrintAgentTrackingService:
    """Sprawdza tracking dla ostatnich zamowien i aktualizuje statusy."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        resolve_carrier_id: Callable[[str], str | None],
        tracking_map: Dict[str, str] | None = None,
    ):
        self.logger = logger
        self.resolve_carrier_id = resolve_carrier_id
        self.tracking_map = tracking_map or ALLEGRO_TRACKING_MAP

    def check_tracking_statuses(self) -> None:
        try:
            access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
            if not access_token:
                self.logger.debug("Brak tokenu Allegro - pomijam sprawdzanie trackingu")
                return

            with get_session() as db:
                carrier_waybills = self._collect_waybills_by_carrier(db)
                if not carrier_waybills:
                    return

                self.logger.debug(
                    "Sprawdzam tracking dla %d zamowien (%d przewoznikow)",
                    sum(len(items) for items in carrier_waybills.values()),
                    len(carrier_waybills),
                )
                self._update_tracking_batches(db, access_token, carrier_waybills)
        except Exception as exc:
            self.logger.warning("Blad sprawdzania statusow przesylek: %s", exc)

    def _collect_waybills_by_carrier(
        self,
        db: Any,
    ) -> Dict[str, List[Tuple[Order, str, str]]]:
        week_ago = int((datetime.now() - timedelta(days=7)).timestamp())
        orders_to_check = db.query(Order).filter(Order.date_add >= week_ago).all()
        carrier_waybills: Dict[str, List[Tuple[Order, str, str]]] = {}

        for order in orders_to_check:
            latest_status = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order.order_id)
                .order_by(desc(OrderStatusLog.timestamp))
                .first()
            )
            current_status = latest_status.status if latest_status else "pobrano"
            if current_status in TERMINAL_TRACKING_STATUSES:
                continue

            waybill = order.delivery_package_nr
            if not waybill:
                continue

            carrier_id = self.resolve_carrier_id(
                order.delivery_method or order.delivery_package_module or ""
            ) or "OTHER"
            carrier_waybills.setdefault(carrier_id, []).append(
                (order, waybill, current_status)
            )

        return carrier_waybills

    def _update_tracking_batches(
        self,
        db: Any,
        access_token: str,
        carrier_waybills: Dict[str, List[Tuple[Order, str, str]]],
    ) -> None:
        for carrier_id, order_items in carrier_waybills.items():
            waybill_to_order = {item[1]: (item[0], item[2]) for item in order_items}
            waybill_list = list(waybill_to_order.keys())

            for start in range(0, len(waybill_list), 20):
                batch = waybill_list[start:start + 20]
                try:
                    tracking_data = fetch_parcel_tracking(access_token, carrier_id, batch)
                except Exception as exc:
                    self.logger.warning(
                        "Blad pobierania trackingu %s: %s",
                        carrier_id,
                        exc,
                    )
                    continue

                self._apply_tracking_response(
                    db,
                    carrier_id,
                    waybill_to_order,
                    tracking_data,
                )

    def _apply_tracking_response(
        self,
        db: Any,
        carrier_id: str,
        waybill_to_order: Dict[str, Tuple[Order, str]],
        tracking_data: Dict[str, Any],
    ) -> None:
        for waybill_data in tracking_data.get("waybills", []):
            waybill = waybill_data.get("waybill", "")
            if waybill not in waybill_to_order:
                continue

            order, current_status = waybill_to_order[waybill]
            events = waybill_data.get("events", [])
            if not events:
                continue

            latest_event = events[0]
            event_type = latest_event.get("type", "")
            new_status = self.tracking_map.get(event_type)
            if not new_status or new_status == current_status:
                continue

            self._apply_order_status(
                db,
                order,
                waybill,
                carrier_id,
                current_status,
                new_status,
                event_type,
            )

    def _apply_order_status(
        self,
        db: Any,
        order: Order,
        waybill: str,
        carrier_id: str,
        current_status: str,
        new_status: str,
        event_type: str,
    ) -> None:
        self.logger.info(
            "Zmiana statusu zamowienia %s: %s -> %s (event: %s)",
            order.order_id,
            current_status,
            new_status,
            event_type,
        )

        try:
            add_order_status(
                db,
                order.order_id,
                new_status,
                tracking_number=waybill,
                courier_code=carrier_id,
                notes=f"Auto-update z Allegro Tracking ({event_type})",
            )
            if new_status == "wyslano" and order.external_order_id:
                self._sync_fulfillment_sent(order)
            db.commit()
        except Exception as exc:
            self.logger.warning("Blad aktualizacji statusu %s: %s", order.order_id, exc)
            db.rollback()

    def _sync_fulfillment_sent(self, order: Order) -> None:
        try:
            update_fulfillment_status(order.external_order_id, "SENT")
        except Exception as exc:
            self.logger.warning(
                "Nie mozna ustawic fulfillment SENT dla %s: %s",
                order.order_id,
                exc,
            )


__all__ = ["PrintAgentTrackingService", "TERMINAL_TRACKING_STATUSES"]