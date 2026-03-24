"""
Integracja z Allegro Shipment Management API ("Wysylam z Allegro").

Endpointy:
- GET /shipment-management/delivery-services - lista dostepnych uslug dostawy
- POST /shipment-management/shipments - tworzenie przesylki (generuje etykiete)
- GET /shipment-management/shipments/{shipmentId} - szczegoly przesylki
- GET /shipment-management/shipments/{shipmentId}/label - pobranie etykiety PDF
- PUT /shipment-management/shipments/commands/cancel - anulowanie przesylki
"""

import logging
import time
from typing import Optional

import requests

from .core import API_BASE_URL, _request_with_retry
from .orders import _get_allegro_token, _refresh_allegro_token

logger = logging.getLogger(__name__)

_delivery_services_cache: Optional[dict] = None
_delivery_services_cache_time: float = 0.0
_CACHE_TTL = 86400  # 24 godziny


def _make_headers(token: str, *, content_type: bool = False,
                  accept_pdf: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if accept_pdf:
        headers["Accept"] = "application/pdf"
    else:
        headers["Accept"] = "application/vnd.allegro.public.v1+json"
    if content_type:
        headers["Content-Type"] = "application/vnd.allegro.public.v1+json"
    return headers


def _call_with_refresh(method, url, endpoint, *, json=None,
                       accept_pdf=False, **kwargs):
    """Wywolaj request z automatycznym odswiezaniem tokenu przy 401."""
    token, refresh = _get_allegro_token()
    headers = _make_headers(
        token, content_type=(json is not None), accept_pdf=accept_pdf,
    )
    refreshed = False

    while True:
        try:
            response = _request_with_retry(
                method, url, endpoint=endpoint, headers=headers,
                json=json, **kwargs,
            )
            return response
        except Exception as exc:
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None,
            )
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                token = _refresh_allegro_token(refresh)
                headers = _make_headers(
                    token, content_type=(json is not None),
                    accept_pdf=accept_pdf,
                )
                continue
            raise


def get_delivery_services() -> list[dict]:
    """Pobierz dostepne uslugi dostawy (cachowane na 24h).

    GET /shipment-management/delivery-services

    Returns
    -------
    list[dict]
        Lista uslug dostawy, kazda zawiera id, name, carrier itp.
    """
    global _delivery_services_cache, _delivery_services_cache_time

    now = time.monotonic()
    if (_delivery_services_cache is not None
            and now - _delivery_services_cache_time < _CACHE_TTL):
        return _delivery_services_cache

    url = f"{API_BASE_URL}/shipment-management/delivery-services"
    response = _call_with_refresh(
        requests.get, url, "delivery-services",
    )
    data = response.json()
    if isinstance(data, list):
        services = data
    else:
        services = data.get("deliveryServices", [])

    _delivery_services_cache = services
    _delivery_services_cache_time = now

    logger.info("Pobrano %d uslug dostawy z Allegro", len(services))
    return services


def invalidate_delivery_services_cache() -> None:
    """Wyczysc cache uslug dostawy."""
    global _delivery_services_cache, _delivery_services_cache_time
    _delivery_services_cache = None
    _delivery_services_cache_time = 0.0


def create_shipment(
    *,
    checkout_form_id: str,
    delivery_service_id: str,
    sender: dict,
    receiver: dict,
    packages: list[dict],
    pickup: Optional[dict] = None,
) -> dict:
    """Utworz przesylke w Allegro Shipment Management.

    POST /shipment-management/shipments

    Parameters
    ----------
    checkout_form_id : str
        UUID zamowienia Allegro (checkout-form).
    delivery_service_id : str
        ID uslugi dostawy (z get_delivery_services()).
    sender : dict
        Dane nadawcy: name, street, city, zipCode, countryCode, phone, email.
    receiver : dict
        Dane odbiorcy: name, street, city, zipCode, countryCode, phone, email,
        opcjonalnie pickupPointId (paczkomat/punkt).
    packages : list[dict]
        Lista paczek z wagami/wymiarami.
    pickup : dict, optional
        Dane odbioru kurierskiego (date itp.).

    Returns
    -------
    dict
        Dane utworzonej przesylki (id, status, itp.).
    """
    url = f"{API_BASE_URL}/shipment-management/shipments"
    body = {
        "deliveryServiceId": delivery_service_id,
        "checkoutForm": {"id": checkout_form_id},
        "sender": sender,
        "receiver": receiver,
        "packages": packages,
    }
    if pickup:
        body["pickup"] = pickup

    response = _call_with_refresh(
        requests.post, url, "shipment-create", json=body,
    )
    result = response.json()

    shipment_id = result.get("id", "?")
    logger.info(
        "Utworzono przesylke %s dla zamowienia %s (usluga: %s)",
        shipment_id, checkout_form_id, delivery_service_id,
    )
    return result


def get_shipment_details(shipment_id: str) -> dict:
    """Pobierz szczegoly przesylki.

    GET /shipment-management/shipments/{shipmentId}

    Parameters
    ----------
    shipment_id : str
        ID przesylki z create_shipment().

    Returns
    -------
    dict
        Szczegoly przesylki: status, waybill, packages itp.
        Statusy: DRAFT, CONFIRMED, DISPATCHED, DELIVERED, CANCELLED.
    """
    url = f"{API_BASE_URL}/shipment-management/shipments/{shipment_id}"
    response = _call_with_refresh(
        requests.get, url, "shipment-details",
    )
    return response.json()


def get_shipment_label(shipment_id: str, *, label_format: str = "PDF") -> bytes:
    """Pobierz etykiete przesylki.

    GET /shipment-management/shipments/{shipmentId}/label

    Parameters
    ----------
    shipment_id : str
        ID przesylki.
    label_format : str
        Format etykiety: "PDF" lub "ZPL". Domyslnie PDF.

    Returns
    -------
    bytes
        Binarne dane etykiety (PDF lub ZPL).

    Raises
    ------
    RuntimeError
        Gdy etykieta nie jest jeszcze dostepna.
    """
    url = f"{API_BASE_URL}/shipment-management/shipments/{shipment_id}/label"
    accept_pdf = label_format.upper() == "PDF"

    token, refresh = _get_allegro_token()
    accept = "application/pdf" if accept_pdf else "application/zpl"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
    }
    refreshed = False

    while True:
        try:
            response = _request_with_retry(
                requests.get, url, endpoint="shipment-label", headers=headers,
            )
            return response.content
        except Exception as exc:
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None,
            )
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                token = _refresh_allegro_token(refresh)
                headers["Authorization"] = f"Bearer {token}"
                continue
            if status_code == 404:
                raise RuntimeError(
                    f"Etykieta nie dostepna dla przesylki {shipment_id} "
                    f"(404 - przesylka moze nie byc jeszcze potwierdzona)"
                ) from exc
            raise


def cancel_shipment(shipment_ids: list[str]) -> dict:
    """Anuluj przesylki.

    PUT /shipment-management/shipments/commands/cancel

    Parameters
    ----------
    shipment_ids : list[str]
        Lista ID przesylek do anulowania.

    Returns
    -------
    dict
        Odpowiedz API z wynikami anulowania.
    """
    url = f"{API_BASE_URL}/shipment-management/shipments/commands/cancel"
    body = {
        "shipmentIds": shipment_ids,
    }

    response = _call_with_refresh(
        requests.put, url, "shipment-cancel", json=body,
    )

    logger.info("Anulowano przesylki: %s", shipment_ids)
    return response.json()
