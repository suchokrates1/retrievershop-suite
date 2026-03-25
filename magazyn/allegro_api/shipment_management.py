"""
Integracja z Allegro Shipment Management API ("Wysylam z Allegro").

Dokumentacja: https://developer.allegro.pl/tutorials/jak-zarzadzac-przesylkami-przez-wysylam-z-allegro-LRVjK7K21sY

Endpointy:
- GET  /shipment-management/delivery-services - lista uslug dostawy
- POST /shipment-management/shipments/create-commands - tworzenie przesylki (async command)
- GET  /shipment-management/shipments/create-commands/{commandId} - status tworzenia
- GET  /shipment-management/shipments/{shipmentId} - szczegoly przesylki
- POST /shipment-management/label - pobranie etykiety PDF/ZPL
- POST /shipment-management/shipments/cancel-commands - anulowanie przesylki (async command)
- GET  /shipment-management/shipments/cancel-commands/{commandId} - status anulowania
"""

import logging
import time
import uuid
from typing import Optional

import requests

from .core import API_BASE_URL, _request_with_retry
from .orders import _get_allegro_token, _refresh_allegro_token

logger = logging.getLogger(__name__)

_delivery_services_cache: Optional[dict] = None
_delivery_services_cache_time: float = 0.0
_CACHE_TTL = 86400  # 24 godziny


def _make_headers(token: str, *, content_type: bool = False,
                  accept_octet: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if accept_octet:
        headers["Accept"] = "application/octet-stream"
    else:
        headers["Accept"] = "application/vnd.allegro.public.v1+json"
    if content_type:
        headers["Content-Type"] = "application/vnd.allegro.public.v1+json"
    return headers


def _call_with_refresh(method, url, endpoint, *, json=None,
                       accept_octet=False, **kwargs):
    """Wywolaj request z automatycznym odswiezaniem tokenu przy 401."""
    token, refresh = _get_allegro_token()
    headers = _make_headers(
        token, content_type=(json is not None), accept_octet=accept_octet,
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
                    accept_octet=accept_octet,
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
        services = data.get("services", data.get("deliveryServices", []))

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
    delivery_method_id: str,
    sender: dict,
    receiver: dict,
    packages: list[dict],
    reference_number: Optional[str] = None,
    label_format: str = "PDF",
    additional_services: Optional[list[str]] = None,
    additional_properties: Optional[dict] = None,
    credentials_id: Optional[str] = None,
) -> dict:
    """Utworz przesylke w Allegro Shipment Management (async command).

    POST /shipment-management/shipments/create-commands

    Operacja asynchroniczna - zwraca commandId.
    Uzyj get_create_command_status() aby sprawdzic status i uzyskac shipmentId.

    Parameters
    ----------
    delivery_method_id : str
        ID metody dostawy (deliveryMethodId z get_delivery_services()).
    sender : dict
        Dane nadawcy: name, company, street, postalCode, city, countryCode, email, phone.
        Opcjonalnie point (jesli adres nadawczy to punkt).
    receiver : dict
        Dane odbiorcy: name, company, street, postalCode, city, countryCode, email, phone.
        Opcjonalnie point (jesli adres odbiorczy to punkt odbioru/paczkomat).
    packages : list[dict]
        Lista paczek. Kazda: type, length, width, height, weight, textOnLabel.
    reference_number : str, optional
        Zewnetrzny ID / sygnatura przesylki.
    label_format : str
        Format etykiety: "PDF" lub "ZPL". Domyslnie PDF.
    additional_services : list[str], optional
        Uslugi dodatkowe (np. "ADDITIONAL_HANDLING").
    additional_properties : dict, optional
        Dodatkowe wlasciwosci (np. {"inpost#sendingMethod": "parcel_locker"}).
    credentials_id : str, optional
        ID umowy wlasnej (jesli nie korzystasz z umowy Allegro).

    Returns
    -------
    dict
        Odpowiedz z commandId, input, opcjonalnie shipmentId.
    """
    url = f"{API_BASE_URL}/shipment-management/shipments/create-commands"

    command_id = str(uuid.uuid4())

    input_data = {
        "deliveryMethodId": delivery_method_id,
        "sender": sender,
        "receiver": receiver,
        "packages": packages,
        "labelFormat": label_format,
    }

    if credentials_id:
        input_data["credentialsId"] = credentials_id
    if reference_number:
        input_data["referenceNumber"] = reference_number
    if additional_services:
        input_data["additionalServices"] = additional_services
    if additional_properties:
        input_data["additionalProperties"] = additional_properties

    body = {
        "commandId": command_id,
        "input": input_data,
    }

    response = _call_with_refresh(
        requests.post, url, "shipment-create", json=body,
    )
    result = response.json()

    logger.info(
        "Wyslano komende tworzenia przesylki commandId=%s (usluga: %s)",
        result.get("commandId", command_id), delivery_method_id,
    )
    return result


def get_create_command_status(command_id: str) -> dict:
    """Sprawdz status asynchronicznego tworzenia przesylki.

    GET /shipment-management/shipments/create-commands/{commandId}

    Returns
    -------
    dict
        status: IN_PROGRESS | SUCCESS | ERROR
        shipmentId: ID przesylki (gdy SUCCESS)
        errors: lista bledow (gdy ERROR)
    """
    url = f"{API_BASE_URL}/shipment-management/shipments/create-commands/{command_id}"
    response = _call_with_refresh(
        requests.get, url, "shipment-create-status",
    )
    return response.json()


def wait_for_shipment_creation(command_id: str, *, timeout: float = 30.0,
                                poll_interval: float = 2.0) -> dict:
    """Poczekaj na zakonczenie tworzenia przesylki.

    Returns
    -------
    dict
        Wynik z get_create_command_status (status SUCCESS lub ERROR).

    Raises
    ------
    TimeoutError
        Gdy przekroczono timeout.
    RuntimeError
        Gdy status ERROR.
    """
    start = time.monotonic()
    while True:
        result = get_create_command_status(command_id)
        status = result.get("status", "")

        if status == "SUCCESS":
            logger.info(
                "Przesylka utworzona: shipmentId=%s (commandId=%s)",
                result.get("shipmentId"), command_id,
            )
            return result

        if status == "ERROR":
            errors = result.get("errors", [])
            error_msg = "; ".join(
                e.get("message", str(e)) for e in errors
            ) if errors else "Nieznany blad"
            logger.error(
                "Blad tworzenia przesylki (commandId=%s): %s", command_id, error_msg,
            )
            raise RuntimeError(f"Blad tworzenia przesylki: {error_msg}")

        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise TimeoutError(
                f"Timeout tworzenia przesylki (commandId={command_id}, "
                f"status={status}, elapsed={elapsed:.1f}s)"
            )

        time.sleep(poll_interval)


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


def get_shipment_label(shipment_ids: list[str], *, page_size: str = "A4",
                       cut_line: bool = True) -> bytes:
    """Pobierz etykiete przesylki.

    POST /shipment-management/label

    Parameters
    ----------
    shipment_ids : list[str]
        Lista ID przesylek.
    page_size : str
        Format strony: "A4" lub "A6". Dotyczy tylko PDF.
    cut_line : bool
        Linie ciecia. Dotyczy tylko PDF A4.

    Returns
    -------
    bytes
        Binarne dane etykiety (PDF lub ZPL).

    Raises
    ------
    RuntimeError
        Gdy etykieta nie jest dostepna.
    """
    url = f"{API_BASE_URL}/shipment-management/label"
    body = {
        "shipmentIds": shipment_ids,
        "pageSize": page_size,
        "cutLine": cut_line,
    }

    response = _call_with_refresh(
        requests.post, url, "shipment-label",
        json=body, accept_octet=True,
    )
    return response.content


def cancel_shipment(shipment_id: str) -> dict:
    """Anuluj przesylke (async command).

    POST /shipment-management/shipments/cancel-commands

    Parameters
    ----------
    shipment_id : str
        ID przesylki do anulowania.

    Returns
    -------
    dict
        Odpowiedz z commandId i input.shipmentId.
    """
    url = f"{API_BASE_URL}/shipment-management/shipments/cancel-commands"
    command_id = str(uuid.uuid4())
    body = {
        "commandId": command_id,
        "input": {
            "shipmentId": shipment_id,
        },
    }

    response = _call_with_refresh(
        requests.post, url, "shipment-cancel", json=body,
    )

    logger.info("Wyslano komende anulowania przesylki %s (commandId=%s)",
                shipment_id, command_id)
    return response.json()


def get_cancel_command_status(command_id: str) -> dict:
    """Sprawdz status anulowania przesylki.

    GET /shipment-management/shipments/cancel-commands/{commandId}

    Returns
    -------
    dict
        status: IN_PROGRESS | SUCCESS | ERROR
    """
    url = f"{API_BASE_URL}/shipment-management/shipments/cancel-commands/{command_id}"
    response = _call_with_refresh(
        requests.get, url, "shipment-cancel-status",
    )
    return response.json()
