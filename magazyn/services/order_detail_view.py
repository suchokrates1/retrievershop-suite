"""Kontekst widoku szczegolow zamowienia."""

from __future__ import annotations

import json

from .order_detail_builder import build_order_detail_context
from .order_presentation import _unix_to_datetime
from .tracking import get_tracking_url

EMAIL_TYPES_MAP = {
    "confirmation": "Potwierdzenie zamowienia",
    "shipment": "Nadanie przesylki",
    "invoice": "Faktura",
    "delivery": "Potwierdzenie dostawy",
    "correction": "Korekta faktury",
}


def build_order_detail_view_context(db, order, *, app_base_url: str = "") -> dict:
    """Zbuduj pelny kontekst template order_detail.html."""
    context = build_order_detail_context(db, order)
    context.update(
        {
            "date_add": _unix_to_datetime(order.date_add),
            "date_confirmed": _unix_to_datetime(order.date_confirmed),
            "tracking_url": get_tracking_url(
                order.courier_code,
                order.delivery_package_module,
                order.delivery_package_nr,
                order.delivery_method,
            ),
            "wfirma_invoice_id": order.wfirma_invoice_id,
            "wfirma_invoice_number": order.wfirma_invoice_number,
            "wfirma_correction_id": order.wfirma_correction_id,
            "wfirma_correction_number": order.wfirma_correction_number,
            "customer_page_url": _customer_page_url(order.customer_token, app_base_url),
        }
    )
    context.update(_email_context(order.emails_sent))
    return context


def _email_context(raw_emails_sent: str | None) -> dict:
    emails_sent = {}
    if raw_emails_sent:
        try:
            emails_sent = json.loads(raw_emails_sent)
        except (ValueError, TypeError):
            emails_sent = {}

    return {
        "email_log": [
            {"type": key, "label": EMAIL_TYPES_MAP.get(key, key), "sent": True}
            for key in EMAIL_TYPES_MAP
            if emails_sent.get(key)
        ],
        "all_email_types": [
            {"type": key, "label": label, "sent": bool(emails_sent.get(key))}
            for key, label in EMAIL_TYPES_MAP.items()
        ],
        "emails_sent": emails_sent,
    }


def _customer_page_url(customer_token: str | None, app_base_url: str) -> str:
    if not customer_token:
        return ""
    base = (app_base_url or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/zamowienie/{customer_token}"


__all__ = ["EMAIL_TYPES_MAP", "build_order_detail_view_context"]