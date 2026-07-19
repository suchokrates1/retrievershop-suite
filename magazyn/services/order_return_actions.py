"""Akcje zwrotow wywolywane z karty zamowienia."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..db import get_session
from ..domain.returns import RETURN_STATUS_IN_TRANSIT, RETURN_STATUS_PENDING
from ..models.orders import Order
from ..models.returns import Return
from .order_status import add_order_status
from .return_core import create_return_from_order, mark_return_as_delivered
from .return_refunds import (
    check_refund_eligibility,
    process_bank_transfer_refund,
    process_refund,
)
from .return_stock import restore_stock_for_return


@dataclass(frozen=True)
class OrderReturnActionResult:
    message: str
    category: str
    not_found: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


def restore_return_stock_for_order(order_id: str) -> OrderReturnActionResult:
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()

        if not return_record:
            return OrderReturnActionResult(
                f"Nie znaleziono zwrotu dla zamowienia {order_id}",
                "error",
            )
        if return_record.stock_restored:
            return OrderReturnActionResult("Stan juz zostal przywrocony", "warning")
        auto_marked_delivered = return_record.status in {RETURN_STATUS_PENDING, RETURN_STATUS_IN_TRANSIT}
        if restore_stock_for_return(return_record.id, accept_pending_as_delivered=True):
            message = "Stan magazynowy zostal przywrocony"
            if auto_marked_delivered:
                message = (
                    "Stan magazynowy zostal przywrocony, a zwrot automatycznie oznaczono jako odebrany"
                )
            return OrderReturnActionResult(
                message,
                "success",
            )
        return OrderReturnActionResult(
            "Nie udalo sie przywrocic stanu - sprawdz czy produkty sa powiazane z magazynem",
            "error",
        )


def create_manual_return_for_order(
    order_id: str,
    form_data: Mapping[str, Any],
) -> OrderReturnActionResult:
    return_note = (form_data.get("notes") or "").strip()
    tracking_number = (form_data.get("return_tracking_number") or "").strip() or None
    initial_status = (
        RETURN_STATUS_IN_TRANSIT
        if form_data.get("mark_in_transit") == "true"
        else RETURN_STATUS_PENDING
    )

    note = "Recznie utworzono zwrot poza Allegro. Koszt przesylki zwrotnej po stronie klienta."
    if return_note:
        note = f"{note} {return_note}"

    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            return OrderReturnActionResult("Nie znaleziono zamowienia", "error", not_found=True)

        existing_return = db.query(Return).filter(
            Return.order_id == order_id,
            Return.status != "cancelled",
        ).first()
        if existing_return:
            return OrderReturnActionResult(
                "Zwrot dla tego zamowienia juz istnieje",
                "warning",
            )

        create_return_from_order(
            order,
            tracking_number=tracking_number,
            return_carrier="MANUAL",
            status=initial_status,
            notes=note,
        )
        add_order_status(
            db,
            order_id,
            "zwrot",
            notes="Recznie utworzono zwrot poza Allegro",
        )

    return OrderReturnActionResult(
        "Utworzono reczny zwrot dla zamowienia",
        "success",
    )


def mark_return_delivered_for_order(order_id: str) -> OrderReturnActionResult:
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()

        if not return_record:
            return OrderReturnActionResult(
                f"Nie znaleziono zwrotu dla zamowienia {order_id}",
                "error",
            )
        if return_record.status in {"delivered", "completed", "not_collected"}:
            return OrderReturnActionResult(
                "Zwrot jest juz oznaczony jako odebrany lub rozliczony",
                "warning",
            )
        if mark_return_as_delivered(return_record.id):
            return OrderReturnActionResult("Zwrot oznaczono jako odebrany", "success")
        return OrderReturnActionResult(
            "Nie udalo sie oznaczyc zwrotu jako odebranego",
            "error",
        )


def refund_eligibility_for_order(order_id: str) -> dict[str, Any]:
    eligible, message, details = check_refund_eligibility(order_id)
    return {"eligible": eligible, "message": message, "details": details}


def process_refund_for_order(
    order_id: str,
    form_data: Mapping[str, Any],
    json_data: Mapping[str, Any] | None,
) -> OrderReturnActionResult:
    json_payload = json_data or {}
    confirm = form_data.get("confirm") == "true" or json_payload.get("confirm") is True
    if not confirm:
        return OrderReturnActionResult("Operacja wymaga potwierdzenia", "error")

    expected_return_id = form_data.get("allegro_return_id") or json_payload.get("allegro_return_id")

    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()

        if not return_record:
            return OrderReturnActionResult(
                "Nie znaleziono zwrotu dla tego zamowienia",
                "error",
            )

        if return_record.allegro_return_id and return_record.allegro_return_id != expected_return_id:
            return OrderReturnActionResult(
                "Blad walidacji - ID zwrotu Allegro nie zgadza sie",
                "error",
            )

    eligible, check_message, _ = check_refund_eligibility(order_id)
    if not eligible:
        return OrderReturnActionResult(
            f"Zwrot nie kwalifikuje sie: {check_message}",
            "error",
        )

    delivery_cost_covered = form_data.get("delivery_cost_covered", "true") == "true"
    reason = form_data.get("reason", "")
    success, message = process_refund(
        order_id=order_id,
        delivery_cost_covered=delivery_cost_covered,
        reason=reason,
    )

    if success:
        return OrderReturnActionResult(
            f"Zwrot pieniedzy zainicjowany pomyslnie! {message}",
            "success",
        )
    return OrderReturnActionResult(f"Blad zwrotu pieniedzy: {message}", "error")


def process_bank_transfer_refund_for_order(
    order_id: str,
    form_data: Mapping[str, Any],
    json_data: Mapping[str, Any] | None,
) -> OrderReturnActionResult:
    json_payload = json_data or {}
    confirm = form_data.get("confirm") == "true" or json_payload.get("confirm") is True
    if not confirm:
        return OrderReturnActionResult("Operacja wymaga potwierdzenia", "error")

    expected_return_id = form_data.get("allegro_return_id") or json_payload.get("allegro_return_id")
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        if not return_record:
            return OrderReturnActionResult(
                "Nie znaleziono zwrotu dla tego zamowienia",
                "error",
            )
        if return_record.allegro_return_id and expected_return_id and (
            return_record.allegro_return_id != expected_return_id
        ):
            return OrderReturnActionResult(
                "Blad walidacji - ID zwrotu Allegro nie zgadza sie",
                "error",
            )

    delivery_raw = form_data.get("delivery_cost_covered", json_payload.get("delivery_cost_covered", "true"))
    delivery_cost_covered = str(delivery_raw).lower() in {"1", "true", "yes", "on"}
    already_raw = form_data.get("already_sent", json_payload.get("already_sent", "true"))
    already_sent = str(already_raw).lower() in {"1", "true", "yes", "on"}

    success, message, payload = process_bank_transfer_refund(
        order_id,
        iban=form_data.get("iban") or json_payload.get("iban") or "",
        recipient=form_data.get("recipient") or json_payload.get("recipient") or "",
        amount=form_data.get("amount") or json_payload.get("amount"),
        title=form_data.get("title") or json_payload.get("title") or "",
        reason=form_data.get("reason") or json_payload.get("reason") or "",
        delivery_cost_covered=delivery_cost_covered,
        already_sent=already_sent,
    )
    if success:
        return OrderReturnActionResult(message, "success", payload=payload or {})
    return OrderReturnActionResult(message, "error", payload=payload or {})


__all__ = [
    "OrderReturnActionResult",
    "create_manual_return_for_order",
    "mark_return_delivered_for_order",
    "process_bank_transfer_refund_for_order",
    "process_refund_for_order",
    "refund_eligibility_for_order",
    "restore_return_stock_for_order",
]