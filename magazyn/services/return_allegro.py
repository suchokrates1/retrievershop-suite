"""Synchronizacja zwrotow z Allegro Customer Returns i tracking paczek."""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

import requests

from ..db import get_session
from ..domain.returns import (
    RETURN_STATUS_CANCELLED,
    RETURN_STATUS_COMPLETED,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_IN_TRANSIT,
    RETURN_STATUS_PENDING,
    map_allegro_return_status,
    map_carrier_to_allegro,
)
from ..models.orders import Order
from ..models.returns import Return
from ..notifications import send_messenger
from ..settings_store import settings_store
from .return_core import add_return_status_log
from .return_notifications import send_return_notification

logger = logging.getLogger(__name__)


def check_allegro_customer_returns(*, log: Optional[logging.Logger] = None) -> Dict[str, int]:
    """Synchronizuj zwroty z Allegro Customer Returns API."""
    from ..allegro_api.core import ALLEGRO_USER_AGENT
    from .order_status import add_order_status

    active_logger = log or logger
    stats = {"created": 0, "existing": 0, "updated": 0, "errors": 0}

    try:
        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            active_logger.warning("Brak tokenu Allegro - pomijam sprawdzanie Customer Returns")
            return stats

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.allegro.beta.v1+json",
            "User-Agent": ALLEGRO_USER_AGENT,
        }
        response = requests.get(
            "https://api.allegro.pl/order/customer-returns?limit=100",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        customer_returns = response.json().get("customerReturns", [])
        active_logger.info("Znaleziono %s zwrotow w Allegro Customer Returns API", len(customer_returns))

        with get_session() as db:
            for return_data in customer_returns:
                allegro_return_id = return_data.get("id")
                allegro_order_id = return_data.get("orderId")
                allegro_status = return_data.get("status")

                try:
                    existing = db.query(Return).filter(
                        Return.allegro_return_id == allegro_return_id,
                    ).first()

                    if existing:
                        updated = _update_existing_return(db, existing, return_data, allegro_status, active_logger)
                        stats["updated" if updated else "existing"] += 1
                        continue

                    order = db.query(Order).filter(Order.external_order_id == allegro_order_id).first()
                    if not order:
                        active_logger.debug(
                            "Zamowienie Allegro %s nie istnieje w bazie - pomijam",
                            allegro_order_id,
                        )
                        continue

                    return_record = _create_return_from_allegro_payload(db, order, return_data, allegro_status)
                    add_order_status(
                        db,
                        order.order_id,
                        "zwrot",
                        notes=f"Wykryto zwrot w Allegro Customer Returns (ref: {return_data.get('referenceNumber')})",
                    )

                    stats["created"] += 1
                    active_logger.info(
                        "Utworzono zwrot #%s dla zamowienia %s (Allegro %s)",
                        return_record.id,
                        order.order_id,
                        allegro_order_id,
                    )
                except Exception as exc:
                    active_logger.error("Blad przetwarzania zwrotu Allegro %s: %s", allegro_return_id, exc)
                    stats["errors"] += 1

            db.commit()
    except Exception as exc:
        active_logger.error("Blad sprawdzania Allegro Customer Returns: %s", exc)
        stats["errors"] += 1

    return stats


def _update_existing_return(db, existing: Return, return_data: dict, allegro_status: str, log: logging.Logger) -> bool:
    updated = False

    parcels = return_data.get("parcels", [])
    if parcels and not existing.return_tracking_number:
        parcel = parcels[0]
        waybill = parcel.get("waybill")
        carrier = parcel.get("carrierId")
        if waybill:
            existing.return_tracking_number = waybill
            existing.return_carrier = carrier
            updated = True
            log.info("Zaktualizowano dane paczki zwrotu #%s: %s (%s)", existing.id, waybill, carrier)

    new_status = map_allegro_return_status(allegro_status)
    allowed_statuses = {
        RETURN_STATUS_IN_TRANSIT,
        RETURN_STATUS_DELIVERED,
        RETURN_STATUS_COMPLETED,
        RETURN_STATUS_CANCELLED,
    }
    if existing.status != new_status and new_status in allowed_statuses:
        old_status = existing.status
        existing.status = new_status
        add_return_status_log(
            db,
            existing.id,
            new_status,
            f"Aktualizacja z Allegro: {allegro_status}",
        )
        updated = True
        log.info("Zaktualizowano zwrot #%s: %s -> %s", existing.id, old_status, new_status)

    return updated


def _create_return_from_allegro_payload(db, order: Order, return_data: dict, allegro_status: str) -> Return:
    parcels = return_data.get("parcels", [])
    return_tracking = None
    return_carrier = None
    if parcels:
        parcel = parcels[0]
        return_tracking = parcel.get("waybill")
        return_carrier = parcel.get("carrierId")

    items = [
        {
            "name": item.get("name"),
            "quantity": item.get("quantity", 1),
            "reason": item.get("reason", {}).get("type"),
            "comment": item.get("reason", {}).get("userComment"),
        }
        for item in return_data.get("items", [])
    ]
    initial_status = map_allegro_return_status(allegro_status)
    buyer = return_data.get("buyer", {})

    return_record = Return(
        order_id=order.order_id,
        status=initial_status,
        customer_name=buyer.get("login") or order.customer_name,
        items_json=json.dumps(items, ensure_ascii=False),
        return_tracking_number=return_tracking,
        return_carrier=return_carrier,
        allegro_return_id=return_data.get("id"),
        notes=f"Allegro ref: {return_data.get('referenceNumber')}",
    )
    db.add(return_record)
    db.flush()

    add_return_status_log(
        db,
        return_record.id,
        initial_status,
        f"Wykryto zwrot w Allegro (ref: {return_data.get('referenceNumber')}, status: {allegro_status})",
    )
    return return_record


def send_pending_return_notifications(*, log: Optional[logging.Logger] = None) -> Dict[str, int]:
    """Wyslij powiadomienia Messenger dla zwrotow bez powiadomienia."""
    active_logger = log or logger
    stats = {"sent": 0, "failed": 0}

    with get_session() as db:
        pending_returns = db.query(Return).filter(Return.messenger_notified.is_(False)).all()
        for return_record in pending_returns:
            success = send_return_notification(
                return_record,
                send_message=send_messenger,
                log=active_logger,
            )
            if success:
                return_record.messenger_notified = True
                stats["sent"] += 1
            else:
                stats["failed"] += 1
        db.commit()

    return stats


def track_return_parcel(return_id: int, *, log: Optional[logging.Logger] = None) -> Optional[str]:
    """Sledz paczke zwrotna przez Allegro API."""
    from ..allegro_api.core import ALLEGRO_USER_AGENT

    active_logger = log or logger

    with get_session() as db:
        return_record = db.query(Return).filter(Return.id == return_id).first()
        if not return_record:
            active_logger.warning("Zwrot #%s nie istnieje", return_id)
            return None

        if not return_record.return_tracking_number:
            active_logger.warning("Zwrot #%s nie ma numeru sledzenia", return_id)
            return None

        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            active_logger.error("Brak tokena dostepu Allegro")
            return None

        try:
            carrier_id = map_carrier_to_allegro(return_record.return_carrier) or "INPOST"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.allegro.public.v1+json",
                "User-Agent": ALLEGRO_USER_AGENT,
            }
            response = requests.get(
                f"https://api.allegro.pl/order/carriers/{carrier_id}/tracking",
                headers=headers,
                params={"waybill": return_record.return_tracking_number},
                timeout=30,
            )

            if response.status_code == 200:
                waybills = response.json().get("waybills", [])
                if waybills:
                    statuses = waybills[0].get("trackingDetails", {}).get("statuses", [])
                    if statuses:
                        latest_status = statuses[-1].get("code")
                        active_logger.debug("Zwrot #%s - status paczki: %s", return_id, latest_status)
                        return latest_status
            else:
                active_logger.warning(
                    "Blad Allegro tracking API: %s - %s",
                    response.status_code,
                    response.text[:200],
                )
        except Exception as exc:
            active_logger.error("Blad sledzenia paczki zwrotnej: %s", exc)

        return None


def check_and_update_return_statuses(*, log: Optional[logging.Logger] = None) -> Dict[str, int]:
    """Sprawdz statusy paczek zwrotnych i zaktualizuj rekordy."""
    active_logger = log or logger
    stats = {"checked": 0, "updated": 0, "errors": 0}

    with get_session() as db:
        active_returns = db.query(Return).filter(
            Return.status.in_([RETURN_STATUS_PENDING, RETURN_STATUS_IN_TRANSIT]),
            Return.return_tracking_number.isnot(None),
        ).all()

        for return_record in active_returns:
            stats["checked"] += 1
            try:
                parcel_status = track_return_parcel(return_record.id, log=active_logger)
                if parcel_status in {"DELIVERED", "PICKED_UP"} and return_record.status != RETURN_STATUS_DELIVERED:
                    return_record.status = RETURN_STATUS_DELIVERED
                    add_return_status_log(
                        db,
                        return_record.id,
                        RETURN_STATUS_DELIVERED,
                        f"Paczka zwrotna dostarczona (status: {parcel_status})",
                    )
                    stats["updated"] += 1
                    active_logger.info("Zwrot #%s - paczka dostarczona", return_record.id)
                elif parcel_status in {"IN_TRANSIT", "OUT_FOR_DELIVERY", "COLLECTED", "RELEASED_FOR_DELIVERY"}:
                    if return_record.status == RETURN_STATUS_PENDING:
                        return_record.status = RETURN_STATUS_IN_TRANSIT
                        add_return_status_log(
                            db,
                            return_record.id,
                            RETURN_STATUS_IN_TRANSIT,
                            f"Paczka w drodze (status: {parcel_status})",
                        )
                        stats["updated"] += 1
                        active_logger.info("Zwrot #%s - paczka w drodze", return_record.id)
            except Exception as exc:
                active_logger.error("Blad sprawdzania statusu zwrotu #%s: %s", return_record.id, exc)
                stats["errors"] += 1

        db.commit()

    return stats


__all__ = [
    "check_allegro_customer_returns",
    "check_and_update_return_statuses",
    "send_pending_return_notifications",
    "track_return_parcel",
]