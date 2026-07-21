"""Anulowanie zamowienia z karty (quick action)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import desc

from .. import allegro_api
from ..db import get_session
from ..models.orders import Order, OrderStatusLog
from ..models.products import ProductSize, Sale
from ..settings_store import settings_store
from .order_status import add_order_status
from .return_refunds import _is_cod_order
from .return_stock import _restore_stock_for_return_item

logger = logging.getLogger(__name__)

CANCEL_ALLOWED_STATUSES = frozenset({
    "pobrano",
    "nieoplacone",
    "wydrukowano",
    "spakowano",
    "blad_druku",
})


@dataclass(frozen=True)
class OrderCancelResult:
    message: str
    category: str
    not_found: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def can_cancel_order(current_status: str) -> bool:
    return current_status in CANCEL_ALLOWED_STATUSES


def _current_order_status(db, order_id: str) -> str:
    last = (
        db.query(OrderStatusLog)
        .filter(OrderStatusLog.order_id == order_id)
        .order_by(desc(OrderStatusLog.timestamp))
        .first()
    )
    return last.status if last else "pobrano"


def _restore_stock_for_order(db, order: Order) -> list[str]:
    """Przywroc stan dla pozycji zamowienia, jesli byly Sale."""
    restored: list[str] = []
    sales_exist = (
        db.query(Sale.id).filter(Sale.order_id == order.order_id).first() is not None
    )
    if not sales_exist:
        return restored

    for op in order.products:
        qty = int(op.quantity or 1)
        if qty <= 0:
            continue
        product_size = None
        if op.product_size_id:
            product_size = db.query(ProductSize).filter(
                ProductSize.id == op.product_size_id
            ).first()
        if not product_size and op.ean:
            product_size = db.query(ProductSize).filter(
                ProductSize.barcode == op.ean
            ).first()
        if not product_size:
            logger.warning(
                "Anulowanie %s: brak ProductSize dla pozycji %s",
                order.order_id,
                op.id,
            )
            continue
        _restore_stock_for_return_item(db, order.order_id, product_size, qty)
        restored.append(f"{op.name or product_size.barcode} +{qty}")
    return restored


def process_cancel_refund(order: Order, reason: str) -> tuple[bool, str]:
    """Zwrot pieniedzy przy anulowaniu (bez rekordu Return)."""
    if not order.external_order_id:
        return False, "Brak external_order_id — nie mozna zainicjowac zwrotu Allegro"

    if _is_cod_order(order):
        return False, (
            "Zamowienie pobraniowe: zaznacz „Zwrócono pieniądze” "
            "(przelew reczny) albo rozlicz zwrot osobno."
        )

    access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
    if not access_token:
        return False, "Brak tokenu Allegro — zaloguj sie lub zaznacz „Zwrócono pieniądze”"

    success, message, _ = allegro_api.initiate_refund(
        access_token=access_token,
        return_id=None,
        order_external_id=order.external_order_id,
        line_items=None,
        delivery_cost_covered=True,
        reason=reason or "Anulowanie zamowienia",
    )
    return success, message


def cancel_order(
    order_id: str,
    *,
    money_already_refunded: bool = False,
    reason: str = "",
) -> OrderCancelResult:
    """Anuluj zamowienie: status, Allegro CANCELLED, korekta, opcjonalnie refund i stan."""
    reason = (reason or "").strip() or "Anulowanie zamowienia"

    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            return OrderCancelResult("Nie znaleziono zamowienia", "error", not_found=True)

        current = _current_order_status(db, order_id)
        if current == "anulowano":
            return OrderCancelResult("Zamowienie jest juz anulowane", "warning")
        if not can_cancel_order(current):
            return OrderCancelResult(
                f"Anulowanie niedostepne w statusie „{current}” "
                f"(dozwolone do spakowano / blad_druku)",
                "error",
            )

        refund_message = ""
        if not money_already_refunded:
            ok, refund_message = process_cancel_refund(order, reason)
            if not ok:
                return OrderCancelResult(refund_message, "error")

        restored = _restore_stock_for_order(db, order)

        notes = reason
        if money_already_refunded:
            notes = f"{reason} (pieniadze juz zwrocone)"
        elif refund_message:
            notes = f"{reason}; zwrot: {refund_message}"

        add_order_status(
            db,
            order_id,
            "anulowano",
            allow_backwards=True,
            notes=notes,
        )

        platform = order.platform
        external_order_id = order.external_order_id
        has_invoice = bool(order.wfirma_invoice_id)
        has_correction = bool(order.wfirma_correction_id)

    allegro_ok = True
    allegro_error: Optional[str] = None
    if platform == "allegro" and external_order_id:
        try:
            from ..allegro_api.fulfillment import update_fulfillment_status

            update_fulfillment_status(external_order_id, "CANCELLED")
        except Exception as exc:
            allegro_ok = False
            allegro_error = str(exc)
            logger.warning(
                "Nie udalo sie ustawic CANCELLED na Allegro dla %s: %s",
                order_id,
                exc,
            )

    correction_number = None
    correction_errors: list[str] = []
    if has_invoice and not has_correction:
        try:
            from .invoice_service import generate_correction_invoice

            correction = generate_correction_invoice(
                order_id=order_id,
                reason=reason,
                return_id=None,
                include_delivery=True,
            )
            if correction.get("success"):
                correction_number = correction.get("invoice_number")
            else:
                correction_errors = list(correction.get("errors") or [])
        except Exception as exc:
            logger.error("Blad korekty przy anulowaniu %s: %s", order_id, exc)
            correction_errors = [str(exc)]

    parts = ["Zamowienie anulowane"]
    if money_already_refunded:
        parts.append("pominięto zwrot (pieniądze już zwrócone)")
    elif refund_message:
        parts.append(f"zwrot: {refund_message}")
    if restored:
        parts.append(f"przywrócono stan: {', '.join(restored)}")
    if correction_number:
        parts.append(f"korekta: {correction_number}")
    elif correction_errors:
        parts.append("uwaga: nie udało się wystawić korekty")
    if not allegro_ok:
        parts.append(f"Allegro CANCELLED nieudane: {allegro_error}")

    category = "success" if allegro_ok or platform != "allegro" else "warning"
    return OrderCancelResult(
        ". ".join(parts) + ".",
        category,
        details={
            "restored": restored,
            "correction_number": correction_number,
            "correction_errors": correction_errors,
            "allegro_ok": allegro_ok,
            "allegro_error": allegro_error,
            "money_already_refunded": money_already_refunded,
        },
    )


__all__ = [
    "CANCEL_ALLOWED_STATUSES",
    "OrderCancelResult",
    "can_cancel_order",
    "cancel_order",
    "process_cancel_refund",
]
