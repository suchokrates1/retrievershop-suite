"""Instrukcje odesłania zwrotu Woo: wybór InPost (kupujący płaci) vs własny."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from flask import render_template

from ..db import get_session
from ..inpost_api.returns import (
    InpostReturnsError,
    create_return_ticket,
    returns_credentials_configured,
)
from ..models.orders import Order
from ..models.returns import Return
from ..settings_store import settings_store
from .email_service import deliver_customer_notification
from .return_core import add_return_status_log

logger = logging.getLogger(__name__)

METHOD_INPOST = "inpost_buyer"
METHOD_SELF = "self"
SELF_DEADLINE_DAYS = 14


def shop_public_base_url() -> str:
    return (settings_store.get("WOO_URL") or "https://retrievershop.pl").rstrip("/")


def instruction_page_url(token: str) -> str:
    return f"{shop_public_base_url()}/instrukcja-zwrotu/?t={token}"


def return_address_dict() -> Dict[str, str]:
    return {
        "company": settings_store.get("SENDER_COMPANY") or "Retriever Shop",
        "name": settings_store.get("SENDER_NAME") or "Alexandra Kaługa",
        "street": settings_store.get("SENDER_STREET") or "Wrocławska 15/7",
        "city": settings_store.get("SENDER_CITY") or "Legnica",
        "postcode": settings_store.get("SENDER_ZIPCODE") or "59-220",
        "phone": settings_store.get("SENDER_PHONE") or "782865895",
        "email": settings_store.get("SENDER_EMAIL") or "kontakt@retrievershop.pl",
    }


def ensure_instruction_token(return_id: int) -> str:
    """Upewnij się, że Return ma token instrukcji i deadline self (14 dni)."""
    with get_session() as db:
        row = db.query(Return).filter(Return.id == return_id).first()
        if not row:
            return ""
        changed = False
        if not row.return_instruction_token:
            row.return_instruction_token = secrets.token_urlsafe(24)
            changed = True
        if not row.return_ship_deadline:
            base = row.created_at or datetime.utcnow()
            row.return_ship_deadline = base + timedelta(days=SELF_DEADLINE_DAYS)
            changed = True
        if changed:
            db.commit()
        return row.return_instruction_token or ""


def _split_name(full: str | None) -> Tuple[str, str]:
    parts = (full or "").strip().split(None, 1)
    if not parts:
        return "Klient", "Zwrot"
    if len(parts) == 1:
        return parts[0], "Zwrot"
    return parts[0], parts[1]


def _order_phone(order: Order) -> str:
    return (order.phone or "").strip()


def get_instructions_payload(token: str) -> Dict[str, Any]:
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "missing_token"}

    with get_session() as db:
        row = (
            db.query(Return)
            .filter(Return.return_instruction_token == token)
            .first()
        )
        if not row:
            return {"ok": False, "error": "not_found"}
        order = db.query(Order).filter(Order.order_id == row.order_id).first()
        phone = _order_phone(order) if order else ""
        display_order = (
            (order.external_order_id if order and order.external_order_id else None)
            or (str(order.shop_order_id) if order and order.shop_order_id else None)
            or row.order_id
        )
        payload = {
            "ok": True,
            "token": token,
            "return_id": row.id,
            "order_id": row.order_id,
            "order_number": display_order,
            "withdrawal_id": row.woo_withdrawal_id,
            "customer_name": row.customer_name or (order.customer_name if order else ""),
            "customer_email": (order.email if order else "") or "",
            "has_phone": bool(phone),
            "phone_hint": (phone[-3:] if len(phone) >= 3 else ""),
            "method": row.return_ship_method,
            "inpost_available": returns_credentials_configured(),
            "return_code": row.return_code,
            "return_code_expires_at": (
                row.return_code_expires_at.isoformat()
                if row.return_code_expires_at
                else None
            ),
            "deadline": (
                row.return_ship_deadline.isoformat()
                if row.return_ship_deadline
                else None
            ),
            "address": return_address_dict(),
            "tracking_number": row.return_tracking_number,
        }
        return payload


def _send_self_ship_email(order: Order, return_row: Return) -> None:
    addr = return_address_dict()
    deadline = return_row.return_ship_deadline
    deadline_txt = deadline.strftime("%d.%m.%Y") if deadline else "14 dni od zgłoszenia"
    ref = return_row.woo_withdrawal_id or str(return_row.id)
    ctx = {
        "order_id": order.external_order_id or order.order_id,
        "return_ref": ref,
        "deadline": deadline_txt,
        "address": addr,
        "order_page_url": "",
    }
    html = render_template("emails/return_self_ship.html", **ctx)
    text = (
        f"Zwrot własny — zamówienie #{ctx['order_id']}\n"
        f"Nr zgłoszenia: {ref}\n"
        f"Wyślij paczkę do {deadline_txt} na:\n"
        f"{addr['company']}\n{addr['name']}\n{addr['street']}\n"
        f"{addr['postcode']} {addr['city']}\n"
        f"Tel: {addr['phone']}\n"
    )
    deliver_customer_notification(
        order,
        subject=f"Instrukcja zwrotu #{ctx['order_id']} — Retriever Shop",
        html_body=html,
        text_body=text,
    )


def _send_inpost_code_email(order: Order, return_row: Return) -> None:
    expires = return_row.return_code_expires_at
    expires_txt = expires.strftime("%d.%m.%Y %H:%M") if expires else ""
    ctx = {
        "order_id": order.external_order_id or order.order_id,
        "return_code": return_row.return_code or "",
        "expires_at": expires_txt,
        "order_page_url": "",
    }
    html = render_template("emails/return_inpost_code.html", **ctx)
    text = (
        f"Szybki zwrot InPost — zamówienie #{ctx['order_id']}\n"
        f"Kod nadania: {ctx['return_code']}\n"
        f"Ważny do: {expires_txt}\n"
        "Nadasz w dowolnym Paczkomacie (Zwrot). Opłatę pobierze InPost przy nadaniu.\n"
    )
    deliver_customer_notification(
        order,
        subject=f"Kod zwrotu InPost #{ctx['order_id']} — Retriever Shop",
        html_body=html,
        text_body=text,
    )


def choose_return_ship_method(
    token: str,
    method: str,
    *,
    pack_size: str = "A",
    phone: str | None = None,
    log: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    active_logger = log or logger
    token = (token or "").strip()
    method = (method or "").strip()
    if method not in {METHOD_INPOST, METHOD_SELF}:
        return {"ok": False, "error": "invalid_method"}

    with get_session() as db:
        row = (
            db.query(Return)
            .filter(Return.return_instruction_token == token)
            .first()
        )
        if not row:
            return {"ok": False, "error": "not_found"}
        order = db.query(Order).filter(Order.order_id == row.order_id).first()
        if not order:
            return {"ok": False, "error": "order_not_found"}

        # Idempotencja: już wybrano tę metodę
        if row.return_ship_method == method:
            if method == METHOD_INPOST and row.return_code:
                return {
                    "ok": True,
                    "already": True,
                    **get_instructions_payload(token),
                }
            if method == METHOD_SELF:
                return {
                    "ok": True,
                    "already": True,
                    **get_instructions_payload(token),
                }

        # Nie pozwalaj zmienić metody jeśli InPost już wygenerował kod
        if row.return_ship_method and row.return_ship_method != method:
            if row.return_code or row.return_ship_method == METHOD_INPOST:
                return {
                    "ok": False,
                    "error": "method_locked",
                    "message": "Metoda odesłania została już wybrana.",
                }

        if method == METHOD_SELF:
            row.return_ship_method = METHOD_SELF
            if not row.return_ship_deadline:
                base = row.created_at or datetime.utcnow()
                row.return_ship_deadline = base + timedelta(days=SELF_DEADLINE_DAYS)
            add_return_status_log(
                db,
                row.id,
                row.status,
                "Klient wybrał zwrot własny (adres + deadline 14 dni)",
            )
            db.commit()
            try:
                _send_self_ship_email(order, row)
            except Exception:
                active_logger.exception("Email return_self_ship failed return=%s", row.id)
            return {"ok": True, **get_instructions_payload(token)}

        # InPost buyer-paid
        if not returns_credentials_configured():
            return {
                "ok": False,
                "error": "inpost_unavailable",
                "message": "Szybki zwrot InPost nie jest jeszcze aktywny. Wybierz zwrot własny.",
            }

        effective_phone = (phone or "").strip() or _order_phone(order)
        if not effective_phone:
            return {
                "ok": False,
                "error": "phone_required",
                "message": "Podaj numer telefonu (9 cyfr) do kodu InPost.",
            }

        first, last = _split_name(row.customer_name or order.customer_name)
        email = (order.email or "").strip()
        if not email:
            return {"ok": False, "error": "email_required"}

        try:
            ticket = create_return_ticket(
                sender_first_name=first,
                sender_last_name=last,
                sender_phone=effective_phone,
                sender_email=email,
                external_reference=str(
                    row.woo_withdrawal_id or order.external_order_id or row.id
                ),
                size=pack_size or "A",
                expiration_days=SELF_DEADLINE_DAYS,
                description=f"Zwrot zamówienia {order.external_order_id or order.order_id}",
            )
        except InpostReturnsError as exc:
            active_logger.error("InPost returns ticket failed: %s %s", exc, exc.details)
            return {
                "ok": False,
                "error": "inpost_api_error",
                "message": str(exc),
            }

        code = str(ticket.get("code") or "").strip()
        if not code:
            return {
                "ok": False,
                "error": "inpost_no_code",
                "message": (
                    "InPost nie zwrócił kodu nadania. Sprawdź ustawienia Returns Portal "
                    "(tryb paperless / customer-paid)."
                ),
            }

        row.return_ship_method = METHOD_INPOST
        row.return_code = code
        row.return_carrier = "INPOST"
        row.return_tracking_number = str(
            ticket.get("trackingNumber") or code
        )
        exp_raw = ticket.get("expirationDate")
        if exp_raw:
            try:
                row.return_code_expires_at = datetime.fromisoformat(
                    str(exp_raw).replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                row.return_code_expires_at = datetime.utcnow() + timedelta(
                    days=SELF_DEADLINE_DAYS
                )
        else:
            row.return_code_expires_at = datetime.utcnow() + timedelta(
                days=SELF_DEADLINE_DAYS
            )
        if phone and not order.phone:
            order.phone = effective_phone
        add_return_status_log(
            db,
            row.id,
            row.status,
            f"Klient wybrał Szybki zwrot InPost, kod={code}",
        )
        db.commit()
        try:
            _send_inpost_code_email(order, row)
        except Exception:
            active_logger.exception("Email return_inpost_code failed return=%s", row.id)
        return {"ok": True, **get_instructions_payload(token)}


__all__ = [
    "METHOD_INPOST",
    "METHOD_SELF",
    "choose_return_ship_method",
    "ensure_instruction_token",
    "get_instructions_payload",
    "instruction_page_url",
    "return_address_dict",
    "shop_public_base_url",
]
