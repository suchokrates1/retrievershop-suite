"""Obsluga kwalifikacji i przetwarzania zwrotow pieniedzy."""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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

COD_PENDING_NOTE = (
    "Pobranie niezaksiegowane przez Allegro — zwrot API zablokowany do wplywu srodkow na konto Allegro"
)
COD_PENDING_MESSAGE = (
    "Pobranie nie zostalo jeszcze zaksiegowane przez Allegro. "
    "Zwrot przez API Allegro jest zablokowany — uzyj zwrotu przelewem bankowym."
)
PKO_IPKO_URL = "https://www.ipko.pl/"
_IBAN_RE = re.compile(r"^PL\d{26}$")


def _is_manual_return(return_record: Return) -> bool:
    return not return_record.allegro_return_id


def _is_cod_order(order: Order) -> bool:
    method = (order.payment_method or "").lower()
    return bool(order.payment_method_cod) or ("pobranie" in method)


def _normalize_iban(value: str) -> str:
    cleaned = re.sub(r"\s+", "", (value or "")).upper()
    if cleaned.isdigit() and len(cleaned) == 26:
        cleaned = f"PL{cleaned}"
    return cleaned


def _parse_amount(value: Any) -> Optional[Decimal]:
    try:
        amount = Decimal(str(value).replace(",", ".")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


def _amount_from_return_items(return_record: Return) -> Decimal:
    try:
        items = json.loads(return_record.items_json or "[]")
    except json.JSONDecodeError:
        items = []
    total = Decimal("0")
    for item in items:
        price = item.get("price") or {}
        try:
            unit = Decimal(str(price.get("amount") or item.get("price_brutto") or "0"))
        except (InvalidOperation, TypeError, ValueError):
            unit = Decimal("0")
        try:
            qty = int(item.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        total += unit * Decimal(qty)
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_bank_transfer_title(order: Order, return_record: Return) -> str:
    ref = ""
    if return_record.notes and "ref:" in return_record.notes.lower():
        ref = return_record.notes.split("ref:")[-1].strip().rstrip(")")
    if not ref:
        ref = order.external_order_id or order.order_id
    return f"Zwrot zamowienia {ref}"[:140]


def _fetch_allegro_return_data(
    access_token: Optional[str],
    return_record: Return,
) -> Optional[Dict[str, Any]]:
    if not access_token or not return_record.allegro_return_id:
        return None
    data, error = allegro_api.get_customer_return(access_token, return_record.allegro_return_id)
    if error:
        logger.warning(
            "Nie mozna pobrac zwrotu Allegro %s: %s",
            return_record.allegro_return_id,
            error,
        )
        return None
    return data


def _build_bank_transfer_details(
    order: Order,
    return_record: Return,
    *,
    allegro_return_data: Optional[Dict[str, Any]] = None,
    include_delivery: bool = True,
) -> Dict[str, Any]:
    bank = allegro_api.extract_return_bank_account(allegro_return_data) or {}
    items_amount = _amount_from_return_items(return_record)
    delivery = Decimal(str(order.delivery_price or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if items_amount <= 0 and order.payment_done:
        total = Decimal(str(order.payment_done)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        items_amount = (total - delivery) if include_delivery else total
        if items_amount < 0:
            items_amount = total

    total_amount = items_amount
    if include_delivery:
        total_amount = (items_amount + delivery).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    title = _build_bank_transfer_title(order, return_record)
    iban = bank.get("iban") or ""
    owner = bank.get("owner") or (order.customer_name or "")
    amount_str = f"{total_amount:.2f}"

    # PKO nie udostepnia publicznego deep-linka z wypelnionym formularzem —
    # otwieramy iPKO i dajemy gotowe dane do wklejenia / skopiowania.
    clipboard_text = "\n".join(
        [
            f"Odbiorca: {owner}",
            f"IBAN: {iban}",
            f"Kwota: {amount_str} PLN",
            f"Tytul: {title}",
        ]
    )

    return {
        "bank_transfer_available": True,
        "iban": iban,
        "account_number": bank.get("account_number") or "",
        "recipient": owner,
        "amount": float(total_amount),
        "items_amount": float(items_amount),
        "delivery_amount": float(delivery),
        "currency": order.currency or "PLN",
        "title": title,
        "clipboard_text": clipboard_text,
        "bank_url": PKO_IPKO_URL,
        "bank_url_label": "Otworz iPKO (PKO BP)",
        "suggested_reason": "Zwrot pobrania przelewem bankowym",
    }


def _cod_pending_details(settlement_details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    details = {
        "cod_settlement_pending": True,
        "allegro_status": "COD_PENDING_SETTLEMENT",
    }
    if settlement_details:
        details.update(settlement_details)
    return details


def _check_cod_settlement(
    access_token: str,
    order: Order,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Zwraca (pending_message, pending_details) gdy pobranie nie jest jeszcze zaksiegowane."""
    if not _is_cod_order(order) or not order.external_order_id:
        return None, None

    checkout_data, cf_error = allegro_api.get_checkout_form(access_token, order.external_order_id)
    if cf_error:
        return f"Blad pobierania danych platnosci: {cf_error}", None

    settlement_status, settlement_details = allegro_api.get_cod_settlement_status(
        access_token,
        checkout_data,
    )
    if settlement_status == "pending":
        return COD_PENDING_MESSAGE, _cod_pending_details(settlement_details)
    return None, None


def _log_cod_pending_once(db, return_record: Return) -> None:
    existing = (
        db.query(ReturnStatusLog)
        .filter(
            ReturnStatusLog.return_id == return_record.id,
            ReturnStatusLog.notes == COD_PENDING_NOTE,
        )
        .first()
    )
    if existing:
        return
    _add_return_status_log(db, return_record.id, return_record.status, COD_PENDING_NOTE)
    db.commit()


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

        order_record = db.query(Order).filter(Order.order_id == order_id).first()
        if not order_record or not order_record.external_order_id:
            return False, "Brak external_order_id zamowienia - nie mozna zrealizowac zwrotu"

        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return False, "Brak tokenu Allegro - zaloguj sie do Allegro"

        pending_message, pending_details = _check_cod_settlement(access_token, order_record)
        if pending_message:
            _log_cod_pending_once(db, return_record)
            return False, pending_message

        if not return_record.allegro_return_id and not _is_manual_return(return_record):
            return False, "Brak ID zwrotu Allegro - zwrot nie pochodzi z Allegro lub nie zostal zsynchronizowany"

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
            if allegro_api.is_cod_not_paid_error(message):
                message = COD_PENDING_MESSAGE
                _log_cod_pending_once(db, return_record)
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
        order_record = db.query(Order).filter(Order.order_id == order_id).first()
        if not order_record:
            return False, "Nie znaleziono zamowienia", None

        allegro_return_data = _fetch_allegro_return_data(access_token, return_record)
        bank_transfer = _build_bank_transfer_details(
            order_record,
            return_record,
            allegro_return_data=allegro_return_data,
            include_delivery=True,
        )

        if not access_token:
            return False, "Brak tokenu Allegro — dostepny zwrot przelewem", bank_transfer

        pending_message, pending_details = _check_cod_settlement(access_token, order_record)
        if pending_message:
            details = pending_details or {}
            details.update(bank_transfer)
            return False, pending_message, details

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
            ok, msg, details = _build_refund_eligibility_details(
                return_record,
                order_record.external_order_id,
                access_token,
                allegro_status=allegro_status,
                message=message,
            )
            if details:
                details.update(bank_transfer)
            else:
                details = bank_transfer
            return ok, msg, details

        if not return_record.allegro_return_id:
            return False, "Brak ID zwrotu Allegro — dostepny zwrot przelewem", bank_transfer

        if not allegro_return_data:
            return_data, error = allegro_api.get_customer_return(
                access_token, return_record.allegro_return_id
            )
            if error:
                return False, f"Blad pobierania danych z Allegro: {error}", bank_transfer
            allegro_return_data = return_data

        can_refund, validation_msg = allegro_api.validate_return_for_refund(allegro_return_data)
        if not can_refund:
            details = dict(bank_transfer)
            details["allegro_status"] = allegro_return_data.get("status")
            details["allegro_refund_blocked"] = True
            return False, f"{validation_msg} — uzyj zwrotu przelewem", details

        ok, msg, details = _build_refund_eligibility_details(
            return_record,
            order_record.external_order_id,
            access_token,
            allegro_return_data=allegro_return_data,
            allegro_status=allegro_return_data.get("status"),
            message=validation_msg,
        )
        if details:
            details.update(bank_transfer)
        else:
            details = bank_transfer
        return ok, msg, details


def process_bank_transfer_refund(
    order_id: str,
    *,
    iban: str,
    recipient: str,
    amount: Any,
    title: str = "",
    reason: str = "",
    delivery_cost_covered: bool = True,
    already_sent: bool = True,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Oznacz zwrot przelewem bankowym i wystaw korekte (bez Allegro Payments API)."""
    normalized_iban = _normalize_iban(iban)
    if not _IBAN_RE.match(normalized_iban):
        return False, "Nieprawidlowy IBAN (oczekiwany format PL + 26 cyfr)", None

    recipient_name = (recipient or "").strip()
    if len(recipient_name) < 2:
        return False, "Podaj imie i nazwisko / nazwe odbiorcy przelewu", None

    parsed_amount = _parse_amount(amount)
    if parsed_amount is None:
        return False, "Podaj poprawna kwote przelewu", None

    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        if not return_record:
            return False, f"Nie znaleziono zwrotu dla zamowienia {order_id}", None
        if return_record.refund_processed:
            return False, "Zwrot pieniedzy juz zostal przetworzony", None

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
            ), None

        order_record = db.query(Order).filter(Order.order_id == order_id).first()
        if not order_record:
            return False, "Nie znaleziono zamowienia", None

        transfer_title = (title or "").strip() or _build_bank_transfer_title(
            order_record, return_record
        )
        effective_reason = (reason or "").strip() or (
            "Zwrot pobrania przelewem bankowym (oznaczono w systemie)"
            if already_sent
            else "Zwrot pobrania przelewem bankowym"
        )

        return_record.status = RETURN_STATUS_COMPLETED
        return_record.refund_processed = True
        note = (
            f"Zwrot przelewem bankowym: {parsed_amount:.2f} PLN → {recipient_name} "
            f"({normalized_iban}), tytul: {transfer_title}. {effective_reason}"
        )
        _add_return_status_log(db, return_record.id, RETURN_STATUS_COMPLETED, note)
        db.commit()

        transfer_payload = {
            "iban": normalized_iban,
            "recipient": recipient_name,
            "amount": float(parsed_amount),
            "currency": order_record.currency or "PLN",
            "title": transfer_title,
            "bank_url": PKO_IPKO_URL,
            "clipboard_text": "\n".join(
                [
                    f"Odbiorca: {recipient_name}",
                    f"IBAN: {normalized_iban}",
                    f"Kwota: {parsed_amount:.2f} PLN",
                    f"Tytul: {transfer_title}",
                ]
            ),
        }

        try:
            from .invoice_service import generate_correction_invoice

            correction = generate_correction_invoice(
                order_id=order_id,
                reason=effective_reason,
                return_id=return_record.id,
                include_delivery=delivery_cost_covered,
            )
            if correction["success"]:
                logger.info(
                    "Korekta %s wystawiona po zwrocie przelewem dla %s",
                    correction["invoice_number"],
                    order_id,
                )
                transfer_payload["correction_number"] = correction["invoice_number"]
            else:
                logger.warning(
                    "Nie udalo sie wystawic korekty po zwrocie przelewem dla %s: %s",
                    order_id,
                    correction["errors"],
                )
                transfer_payload["correction_errors"] = correction["errors"]
        except Exception as exc:
            logger.error("Blad wystawiania korekty po zwrocie przelewem %s: %s", order_id, exc)
            transfer_payload["correction_errors"] = [str(exc)]

        msg = (
            f"Oznaczono zwrot przelewem ({parsed_amount:.2f} PLN). "
            f"Dane: {recipient_name}, {normalized_iban}."
        )
        if transfer_payload.get("correction_number"):
            msg += f" Korekta: {transfer_payload['correction_number']}."
        elif transfer_payload.get("correction_errors"):
            msg += " Uwaga: nie udalo sie wystawic/wyslac korekty — sprawdz logi."

        return True, msg, transfer_payload


__all__ = [
    "check_refund_eligibility",
    "process_bank_transfer_refund",
    "process_refund",
]