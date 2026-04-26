"""
Wysylanie faktur do zamowien Allegro.

Endpointy:
- POST /order/checkout-forms/{id}/invoices - utworz metadane faktury
- PUT  /order/checkout-forms/{id}/invoices/{invoiceId}/file - upload PDF
"""
import logging
from typing import Optional

import requests

from .core import (
    API_BASE_URL,
    _request_with_retry,
)
from .tokens import get_allegro_token as _get_allegro_token, refresh_allegro_token as _refresh_allegro_token

logger = logging.getLogger(__name__)


def upload_invoice_to_allegro(
    checkout_form_id: str,
    invoice_number: str,
    pdf_data: bytes,
    *,
    file_name: Optional[str] = None,
) -> dict:
    """
    Upload faktury PDF do zamowienia Allegro.

    Sklada sie z 2 krokow:
    1. POST /order/checkout-forms/{id}/invoices - rejestracja faktury
    2. PUT  /order/checkout-forms/{id}/invoices/{invoiceId}/file - upload pliku

    Parameters
    ----------
    checkout_form_id : str
        ID zamowienia Allegro (UUID).
    invoice_number : str
        Numer faktury (np. "FV/2025/06/001").
    pdf_data : bytes
        Zawartosc pliku PDF.
    file_name : str, optional
        Nazwa pliku. Domyslnie generowana z numeru faktury.

    Returns
    -------
    dict
        {"invoice_id": str, "invoice_number": str}
    """
    if not pdf_data:
        raise ValueError("Pusty plik PDF")

    if file_name is None:
        safe_number = invoice_number.replace("/", "_").replace("\\", "_")
        file_name = f"{safe_number}.pdf"

    token, refresh = _get_allegro_token()

    # Krok 1: Zarejestruj fakture
    invoice_id = _create_invoice_metadata(
        checkout_form_id, invoice_number, file_name, token, refresh
    )

    # Krok 2: Upload PDF
    _upload_invoice_file(
        checkout_form_id, invoice_id, pdf_data, file_name, token, refresh
    )

    logger.info(
        "Faktura %s wyslana do zamowienia Allegro %s (invoice_id=%s)",
        invoice_number, checkout_form_id, invoice_id,
    )

    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
    }


def _create_invoice_metadata(
    checkout_form_id: str,
    invoice_number: str,
    file_name: str,
    token: str,
    refresh: str,
) -> str:
    """Krok 1: POST /order/checkout-forms/{id}/invoices."""
    url = f"{API_BASE_URL}/order/checkout-forms/{checkout_form_id}/invoices"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
    }
    payload = {
        "file": {
            "name": file_name,
        },
        "invoiceNumber": invoice_number,
    }

    try:
        resp = _request_with_retry(
            requests.post,
            url,
            endpoint="order_invoices_create",
            headers=headers,
            json=payload,
        )
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status == 401:
            new_token = _refresh_allegro_token(refresh)
            headers["Authorization"] = f"Bearer {new_token}"
            resp = _request_with_retry(
                requests.post,
                url,
                endpoint="order_invoices_create",
                headers=headers,
                json=payload,
            )
        else:
            raise

    data = resp.json()
    invoice_id = data.get("id")
    if not invoice_id:
        raise RuntimeError(f"Allegro nie zwrocilo invoice_id: {data}")

    return invoice_id


def _upload_invoice_file(
    checkout_form_id: str,
    invoice_id: str,
    pdf_data: bytes,
    file_name: str,
    token: str,
    refresh: str,
) -> None:
    """Krok 2: PUT /order/checkout-forms/{id}/invoices/{invoiceId}/file."""
    url = (
        f"{API_BASE_URL}/order/checkout-forms/{checkout_form_id}"
        f"/invoices/{invoice_id}/file"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/pdf",
    }

    try:
        _request_with_retry(
            requests.put,
            url,
            endpoint="order_invoices_upload",
            headers=headers,
            data=pdf_data,
        )
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status == 401:
            new_token = _refresh_allegro_token(refresh)
            headers["Authorization"] = f"Bearer {new_token}"
            _request_with_retry(
                requests.put,
                url,
                endpoint="order_invoices_upload",
                headers=headers,
                data=pdf_data,
            )
        else:
            raise
