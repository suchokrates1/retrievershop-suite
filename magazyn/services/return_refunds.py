"""Obsluga kwalifikacji i przetwarzania zwrotow pieniedzy."""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from .. import allegro_api
from ..db import get_session
from ..domain.returns import (
    RETURN_STATUS_CANCELLED,
    RETURN_STATUS_COMPLETED,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_IN_TRANSIT,
)
from ..models.orders import Order
from ..models.returns import Return, ReturnStatusLog
from ..settings_store import settings_store

logger = logging.getLogger(__name__)


def _add_return_status_log(db, return_id: int, status: str, notes: str = None) -> None:
    db.add(ReturnStatusLog(return_id=return_id, status=status, notes=notes))


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

        allowed = (RETURN_STATUS_DELIVERED, RETURN_STATUS_IN_TRANSIT, RETURN_STATUS_COMPLETED)
        if return_record.status not in allowed:
            return False, (
                "Zwrot musi byc w statusie 'delivered', 'in_transit' lub 'completed'. "
                f"Aktualny status: {return_record.status}"
            )

        if not return_record.allegro_return_id:
            return False, "Brak ID zwrotu Allegro - zwrot nie pochodzi z Allegro lub nie zostal zsynchronizowany"

        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return False, "Brak tokenu Allegro - zaloguj sie do Allegro"

        order_record = db.query(Order).filter(Order.order_id == order_id).first()
        if not order_record or not order_record.external_order_id:
            return False, "Brak external_order_id zamowienia - nie mozna zrealizowac zwrotu"

        success, message, _response_data = allegro_api.initiate_refund(
            access_token=access_token,
            return_id=return_record.allegro_return_id,
            order_external_id=order_record.external_order_id,
            delivery_cost_covered=delivery_cost_covered,
            reason=reason,
        )

        if success:
            return_record.status = RETURN_STATUS_COMPLETED
            return_record.refund_processed = True
            _add_return_status_log(
                db,
                return_record.id,
                RETURN_STATUS_COMPLETED,
                f"Zwrot pieniedzy zainicjowany przez Allegro API. {reason or ''}",
            )
            db.commit()

            logger.info("Zwrot pieniedzy dla zamowienia %s przetworzony pomyslnie", order_id)

            try:
                from .invoice_service import generate_correction_invoice

                correction = generate_correction_invoice(
                    order_id=order_id,
                    reason=reason or "Zwrot produktow",
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

        allowed = (RETURN_STATUS_DELIVERED, RETURN_STATUS_IN_TRANSIT, RETURN_STATUS_COMPLETED)
        if return_record.status not in allowed:
            return False, (
                "Zwrot musi byc w statusie 'delivered', 'in_transit' lub 'completed'. "
                f"Aktualny: {return_record.status}"
            ), None

        if not return_record.allegro_return_id:
            return False, "Brak ID zwrotu Allegro", None

        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return False, "Brak tokenu Allegro", None

        return_data, error = allegro_api.get_customer_return(access_token, return_record.allegro_return_id)
        if error:
            return False, f"Blad pobierania danych z Allegro: {error}", None

        can_refund, validation_msg = allegro_api.validate_return_for_refund(return_data)
        if not can_refund:
            return False, validation_msg, None

        refund = return_data.get("refund") or {}
        total_value = refund.get("totalValue") or {}
        delivery = refund.get("delivery") or {}

        total_amount = float(total_value.get("amount", 0))
        currency = total_value.get("currency", "PLN")

        if total_amount <= 0:
            items = return_data.get("items", [])
            for item in items:
                price = item.get("price", {})
                item_amount = float(price.get("amount", 0))
                quantity = int(item.get("quantity", 1))
                total_amount += item_amount * quantity
                if currency == "PLN":
                    currency = price.get("currency", "PLN")

        details = {
            "allegro_status": return_data.get("status"),
            "total_amount": total_amount,
            "currency": currency,
            "delivery_amount": float(delivery.get("amount", 0)) if delivery else 0,
            "items": return_data.get("items", []),
            "allegro_return_id": return_record.allegro_return_id,
        }

        return True, validation_msg, details


__all__ = ["check_refund_eligibility", "process_refund"]