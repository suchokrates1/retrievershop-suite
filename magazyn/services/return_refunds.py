"""Obsluga kwalifikacji i przetwarzania zwrotow pieniedzy."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .. import allegro_api
from ..db import get_session
from ..domain.returns import (
    RETURN_STATUS_CANCELLED,
    RETURN_STATUS_COMPLETED,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_IN_TRANSIT,
    RETURN_STATUS_NOT_COLLECTED,
)
from ..models.orders import Order
from ..models.returns import Return, ReturnStatusLog
from ..settings_store import settings_store

logger = logging.getLogger(__name__)


def _is_manual_return(return_record: Return) -> bool:
    return not return_record.allegro_return_id


def _is_stock_restored_refund_override(return_record: Return) -> bool:
    return bool(
        return_record.stock_restored
        and return_record.status in {
            RETURN_STATUS_DELIVERED,
            RETURN_STATUS_NOT_COLLECTED,
            RETURN_STATUS_COMPLETED,
        }
    )


def _add_return_status_log(db, return_id: int, status: str, notes: str = None) -> None:
    db.add(ReturnStatusLog(return_id=return_id, status=status, notes=notes))


def _resolve_return_items(
    return_record: Return,
    allegro_return_data: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Zwroc pozycje faktycznie objete zwrotem (Allegro API ma pierwszenstwo)."""
    if allegro_return_data and allegro_return_data.get("items"):
        return allegro_return_data["items"]

    try:
        parsed = json.loads(return_record.items_json or "[]")
    except json.JSONDecodeError:
        parsed = []

    return parsed or None


def _build_refund_execution(
    return_record: Return,
    order_external_id: str,
    access_token: str,
    *,
    allegro_return_data: Optional[Dict[str, Any]] = None,
    delivery_cost_covered: bool = False,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Przygotuj line_items dla Allegro payments/refunds."""
    return_items = _resolve_return_items(return_record, allegro_return_data)
    if not return_items:
        return None, None

    checkout_data, cf_error = allegro_api.get_checkout_form(access_token, order_external_id)
    if cf_error:
        return None, f"Blad pobierania danych z Allegro: {cf_error}"

    details, build_error = allegro_api.build_partial_refund_details(
        return_items,
        checkout_data,
        delivery_cost_covered=delivery_cost_covered,
    )
    if build_error:
        return None, build_error

    return details["line_items"], None


def _build_refund_eligibility_details(
    return_record: Return,
    order_external_id: str,
    access_token: str,
    *,
    allegro_return_data: Optional[Dict[str, Any]] = None,
    allegro_status: str,
    message: str,
) -> Tuple[bool, str, Optional[Dict]]:
    return_items = _resolve_return_items(return_record, allegro_return_data)
    checkout_data, cf_error = allegro_api.get_checkout_form(access_token, order_external_id)
    if cf_error:
        return False, f"Blad pobierania danych z Allegro: {cf_error}", None

    if return_items:
        details, build_error = allegro_api.build_partial_refund_details(
            return_items,
            checkout_data,
            delivery_cost_covered=False,
        )
        if build_error:
            return False, build_error, None
        details["allegro_status"] = allegro_status
        details["allegro_return_id"] = return_record.allegro_return_id
        return True, message, details

    details = allegro_api.build_checkout_refund_details(checkout_data)
    return True, message, {
        "allegro_status": allegro_status,
        "total_amount": details["total_amount"],
        "currency": details["currency"],
        "delivery_amount": details["delivery_amount"],
        "items": details["items"],
        "returned_items": [],
        "is_partial": False,
        "allegro_return_id": return_record.allegro_return_id,
    }


def process_refund(
    order_id: str,
    delivery_cost_covered: bool = True,
    reason: str = None,
) -> Tuple[bool, str]:
    """Przetworz zwrot pieniedzy dla zamowienia."""
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()

        if not return_record:
            return False, f"Nie znaleziono zwrotu dla zamowienia {order_id}"

        if return_record.refund_processed:
            return False, "Zwrot pieniedzy juz zostal przetworzony"

        allowed = (
            RETURN_STATUS_DELIVERED,
            RETURN_STATUS_IN_TRANSIT,
            RETURN_STATUS_NOT_COLLECTED,
            RETURN_STATUS_COMPLETED,
        )
        if return_record.status not in allowed:
            return False, (
                "Zwrot musi byc w statusie 'delivered', 'in_transit', 'not_collected' lub 'completed'. "
                f"Aktualny status: {return_record.status}"
            )

        if not return_record.allegro_return_id and not _is_manual_return(return_record):
            return False, "Brak ID zwrotu Allegro - zwrot nie pochodzi z Allegro lub nie zostal zsynchronizowany"

        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return False, "Brak tokenu Allegro - zaloguj sie do Allegro"

        order_record = db.query(Order).filter(Order.order_id == order_id).first()
        if not order_record or not order_record.external_order_id:
            return False, "Brak external_order_id zamowienia - nie mozna zrealizowac zwrotu"

        effective_reason = reason
        if not effective_reason and return_record.status == RETURN_STATUS_NOT_COLLECTED:
            effective_reason = "Nie odebrano przesylki"
        elif not effective_reason and _is_stock_restored_refund_override(return_record):
            effective_reason = "Zwrot potwierdzony po przywroceniu stanu"
        elif not effective_reason and _is_manual_return(return_record):
            effective_reason = "Ręczny zwrot poza Allegro"

        allegro_return_data = None
        if return_record.allegro_return_id and not _is_stock_restored_refund_override(return_record):
            allegro_return_data, allegro_error = allegro_api.get_customer_return(
                access_token,
                return_record.allegro_return_id,
            )
            if allegro_error:
                return False, f"Blad pobierania danych zwrotu z Allegro: {allegro_error}"

        line_items, build_error = _build_refund_execution(
            return_record,
            order_record.external_order_id,
            access_token,
            allegro_return_data=allegro_return_data,
            delivery_cost_covered=delivery_cost_covered,
        )
        if build_error:
            return False, build_error

        success, message, _response_data = allegro_api.initiate_refund(
            access_token=access_token,
            return_id=None if _is_stock_restored_refund_override(return_record) else return_record.allegro_return_id,
            order_external_id=order_record.external_order_id,
            line_items=line_items,
            delivery_cost_covered=delivery_cost_covered,
            reason=effective_reason,
        )

        if success:
            return_record.status = RETURN_STATUS_COMPLETED
            return_record.refund_processed = True
            _add_return_status_log(
                db,
                return_record.id,
                RETURN_STATUS_COMPLETED,
                f"Zwrot pieniedzy zainicjowany przez Allegro API. {effective_reason or ''}",
            )
            db.commit()

            logger.info("Zwrot pieniedzy dla zamowienia %s przetworzony pomyslnie", order_id)

            try:
                from .invoice_service import generate_correction_invoice

                correction = generate_correction_invoice(
                    order_id=order_id,
                    reason=effective_reason or "Zwrot produktow",
                    return_id=return_record.id,
                    include_delivery=delivery_cost_covered,
                )
                if correction["success"]:
                    logger.info(
                        "Korekta %s wystawiona dla zamowienia %s",
                        correction["invoice_number"],
                        order_id,
                    )
                else:
                    logger.warning(
                        "Nie udalo sie wystawic korekty dla zamowienia %s: %s",
                        order_id,
                        correction["errors"],
                    )
            except Exception as exc:
                logger.error("Blad wystawiania korekty dla zamowienia %s: %s", order_id, exc)
        else:
            logger.error("Blad zwrotu pieniedzy dla zamowienia %s: %s", order_id, message)

        return success, message


def check_refund_eligibility(order_id: str) -> Tuple[bool, str, Optional[Dict]]:
    """Sprawdz, czy zamowienie kwalifikuje sie do zwrotu pieniedzy."""
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()

        if not return_record:
            return False, "Brak zwrotu dla tego zamowienia", None

        if return_record.refund_processed:
            return False, "Zwrot pieniedzy juz zostal przetworzony", None

        if return_record.status == RETURN_STATUS_CANCELLED:
            return False, "Zwrot zostal anulowany", None

        allowed = (
            RETURN_STATUS_DELIVERED,
            RETURN_STATUS_IN_TRANSIT,
            RETURN_STATUS_NOT_COLLECTED,
            RETURN_STATUS_COMPLETED,
        )
        if return_record.status not in allowed:
            return False, (
                "Zwrot musi byc w statusie 'delivered', 'in_transit', 'not_collected' lub 'completed'. "
                f"Aktualny: {return_record.status}"
            ), None

        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return False, "Brak tokenu Allegro", None

        if _is_manual_return(return_record) or _is_stock_restored_refund_override(return_record):
            if return_record.status == RETURN_STATUS_NOT_COLLECTED:
                allegro_status = "NOT_COLLECTED"
                message = "Zwrot gotowy do realizacji: nie odebrano przesylki"
            elif _is_manual_return(return_record):
                allegro_status = "MANUAL_RETURN"
                message = "Zwrot gotowy do realizacji: ręczny zwrot"
            else:
                allegro_status = "STOCK_RESTORED"
                message = "Zwrot gotowy do realizacji: potwierdzono zwrot przez przywrocenie stanu"
            return _build_refund_eligibility_details(
                return_record,
                return_record.order.external_order_id,
                access_token,
                allegro_status=allegro_status,
                message=message,
            )

        if not return_record.allegro_return_id:
            return False, "Brak ID zwrotu Allegro", None

        return_data, error = allegro_api.get_customer_return(access_token, return_record.allegro_return_id)
        if error:
            return False, f"Blad pobierania danych z Allegro: {error}", None

        can_refund, validation_msg = allegro_api.validate_return_for_refund(return_data)
        if not can_refund:
            return False, validation_msg, None

        return _build_refund_eligibility_details(
            return_record,
            return_record.order.external_order_id,
            access_token,
            allegro_return_data=return_data,
            allegro_status=return_data.get("status"),
            message=validation_msg,
        )


__all__ = ["check_refund_eligibility", "process_refund"]