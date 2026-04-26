"""
Zarzadzanie statusami realizacji zamowien Allegro (fulfillment).

Endpointy:
- PUT /order/checkout-forms/{id}/fulfillment - zmiana statusu realizacji
- POST /order/checkout-forms/{id}/shipments - dodanie numeru przesylki
- GET /order/checkout-forms/{id}/shipments - lista przesylek

Dostepne statusy fulfillment:
  NEW, PROCESSING, READY_FOR_SHIPMENT, SENT, READY_FOR_PICKUP, PICKED_UP, CANCELLED
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

VALID_FULFILLMENT_STATUSES = frozenset({
    "NEW",
    "PROCESSING",
    "READY_FOR_SHIPMENT",
    "SENT",
    "READY_FOR_PICKUP",
    "PICKED_UP",
    "CANCELLED",
})


def _make_headers(token: str, *, content_type: bool = False) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    if content_type:
        headers["Content-Type"] = "application/vnd.allegro.public.v1+json"
    return headers


def _call_with_refresh(method, url, endpoint, *, json=None, **kwargs):
    """Wywolaj request z automatycznym odswiezaniem tokenu przy 401."""
    token, refresh = _get_allegro_token()
    headers = _make_headers(token, content_type=(json is not None))
    refreshed = False

    while True:
        try:
            response = _request_with_retry(
                method,
                url,
                endpoint=endpoint,
                headers=headers,
                json=json,
                **kwargs,
            )
            return response
        except Exception as exc:
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                token = _refresh_allegro_token(refresh)
                headers = _make_headers(token, content_type=(json is not None))
                continue
            raise


def update_fulfillment_status(
    checkout_form_id: str,
    status: str,
    *,
    shipment_summary: Optional[dict] = None,
) -> dict:
    """Zmien status realizacji zamowienia.

    PUT /order/checkout-forms/{id}/fulfillment

    Parameters
    ----------
    checkout_form_id : str
        UUID zamowienia Allegro.
    status : str
        Nowy status: NEW, PROCESSING, READY_FOR_SHIPMENT, SENT,
        READY_FOR_PICKUP, PICKED_UP, CANCELLED.
    shipment_summary : dict, optional
        Podsumowanie przesylki, np. {"lineItemsSent": "ALL"}.

    Returns
    -------
    dict
        Odpowiedz API z aktualnym stanem fulfillment.

    Raises
    ------
    ValueError
        Gdy podany status nie jest prawidlowy.
    """
    if status not in VALID_FULFILLMENT_STATUSES:
        raise ValueError(
            f"Nieprawidlowy status fulfillment: {status}. "
            f"Dozwolone: {', '.join(sorted(VALID_FULFILLMENT_STATUSES))}"
        )

    url = f"{API_BASE_URL}/order/checkout-forms/{checkout_form_id}/fulfillment"
    body = {"status": status}
    if shipment_summary:
        body["shipmentSummary"] = shipment_summary

    response = _call_with_refresh(
        requests.put, url, "fulfillment-update", json=body
    )

    logger.info(
        "Fulfillment %s -> %s dla zamowienia %s",
        "zmieniony", status, checkout_form_id,
    )
    # Allegro PUT fulfillment moze zwrocic 204 No Content (puste body)
    if response.status_code == 204 or not response.content:
        return {"status": status}
    return response.json()


def add_shipment_tracking(
    checkout_form_id: str,
    *,
    carrier_id: str,
    waybill: str,
    line_items_sent: str = "ALL",
) -> dict:
    """Dodaj numer przesylki do zamowienia.

    POST /order/checkout-forms/{id}/shipments

    Parameters
    ----------
    checkout_form_id : str
        UUID zamowienia Allegro.
    carrier_id : str
        Identyfikator przewoznika: INPOST, DHL, DPD, POCZTA_POLSKA,
        ALLEGRO, UPS, GLS, FEDEX, OTHER.
    waybill : str
        Numer listu przewozowego / tracking number.
    line_items_sent : str
        Jakie pozycje wysylane: "ALL", "SOME", "NONE".

    Returns
    -------
    dict
        Dane utworzonej przesylki z Allegro.
    """
    url = f"{API_BASE_URL}/order/checkout-forms/{checkout_form_id}/shipments"
    body = {
        "carrierId": carrier_id,
        "waybill": waybill,
        "carrierName": None,
        "lineItemsSent": line_items_sent,
    }

    response = _call_with_refresh(
        requests.post, url, "shipment-add", json=body
    )

    logger.info(
        "Dodano przesylke %s/%s do zamowienia %s",
        carrier_id, waybill, checkout_form_id,
    )
    return response.json()


def get_shipment_tracking_numbers(checkout_form_id: str) -> list[dict]:
    """Pobierz liste przesylek przypisanych do zamowienia.

    GET /order/checkout-forms/{id}/shipments

    Parameters
    ----------
    checkout_form_id : str
        UUID zamowienia Allegro.

    Returns
    -------
    list[dict]
        Lista przesylek, kazda zawiera carrierId, waybill, itp.
    """
    url = f"{API_BASE_URL}/order/checkout-forms/{checkout_form_id}/shipments"

    response = _call_with_refresh(
        requests.get, url, "shipment-list"
    )

    data = response.json()
    shipments = data.get("shipments", [])
    logger.debug(
        "Zamowienie %s: %d przesylek", checkout_form_id, len(shipments)
    )
    return shipments
