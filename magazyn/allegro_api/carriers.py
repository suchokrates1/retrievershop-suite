"""
Lista przewoznikow Allegro i mapowanie metod dostawy.

Endpointy:
- GET /order/carriers - lista dostepnych przewoznikow

Mapowanie:
- delivery_method.name z zamowienia -> carrier_id dla tracking
- delivery_method.name -> delivery_service_id dla Shipment Management
"""

import logging
import time
from typing import Optional

import requests

from .core import API_BASE_URL, _request_with_retry
from .tokens import get_allegro_token as _get_allegro_token, refresh_allegro_token as _refresh_allegro_token
from ..status_config import SHIPMENT_TRACKING_MAP

logger = logging.getLogger(__name__)
TRACKING_TO_INTERNAL = SHIPMENT_TRACKING_MAP

_carriers_cache: Optional[list] = None
_carriers_cache_time: float = 0.0
_CACHE_TTL = 86400  # 24 godziny

# Mapowanie nazw metod dostawy Allegro na ID przewoznika
# Uzywane do add_shipment_tracking() i fetch_parcel_tracking()
DELIVERY_METHOD_TO_CARRIER = {
    "allegro paczkomaty inpost": "INPOST",
    "allegro kurier inpost": "INPOST",
    "allegro mini przesylka inpost": "INPOST",
    "allegro kurier dpd": "DPD",
    "allegro kurier dhl": "DHL",
    "allegro kurier ups": "UPS",
    "allegro kurier gls": "GLS",
    "allegro kurier pocztex": "POCZTA_POLSKA",
    "allegro poczta polska": "POCZTA_POLSKA",
    "allegro one box": "ALLEGRO",
    "allegro one punkt": "ALLEGRO",
    "allegro one kurier": "ALLEGRO",
    "allegro automat orlen paczka": "ORLEN_PACZKA",
    "allegro kurier fedex": "FEDEX",
}



def _call_with_refresh(method, url, endpoint, **kwargs):
    """Wywolaj request z automatycznym odswiezaniem tokenu przy 401."""
    token, refresh = _get_allegro_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    refreshed = False

    while True:
        try:
            response = _request_with_retry(
                method, url, endpoint=endpoint, headers=headers, **kwargs,
            )
            return response
        except Exception as exc:
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None,
            )
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                token = _refresh_allegro_token(refresh)
                headers["Authorization"] = f"Bearer {token}"
                continue
            raise


def fetch_carriers() -> list[dict]:
    """Pobierz liste przewoznikow z Allegro (cachowane na 24h).

    GET /order/carriers

    Returns
    -------
    list[dict]
        Lista przewoznikow z id i name.
    """
    global _carriers_cache, _carriers_cache_time

    now = time.monotonic()
    if _carriers_cache is not None and now - _carriers_cache_time < _CACHE_TTL:
        return _carriers_cache

    url = f"{API_BASE_URL}/order/carriers"
    response = _call_with_refresh(requests.get, url, "carriers")
    data = response.json()
    if isinstance(data, list):
        carriers = data
    else:
        carriers = data.get("carriers", [])

    _carriers_cache = carriers
    _carriers_cache_time = now

    logger.info("Pobrano %d przewoznikow z Allegro", len(carriers))
    return carriers


def invalidate_carriers_cache() -> None:
    """Wyczysc cache przewoznikow."""
    global _carriers_cache, _carriers_cache_time
    _carriers_cache = None
    _carriers_cache_time = 0.0


def resolve_carrier_id(delivery_method_name: str) -> str:
    """Rozpoznaj ID przewoznika na podstawie nazwy metody dostawy.

    Parameters
    ----------
    delivery_method_name : str
        Nazwa metody dostawy z zamowienia Allegro
        (np. "Allegro Paczkomaty InPost 24/7").

    Returns
    -------
    str
        ID przewoznika ("INPOST", "DPD", "DHL" itp.) lub "OTHER".
    """
    if not delivery_method_name:
        return "OTHER"

    name_lower = delivery_method_name.lower().strip()

    # Probuj dokladne dopasowanie (bez 24/7, standard itp.)
    for pattern, carrier_id in DELIVERY_METHOD_TO_CARRIER.items():
        if pattern in name_lower:
            return carrier_id

    # Ogolne dopasowanie po nazwie przewoznika
    carrier_keywords = {
        "inpost": "INPOST",
        "dpd": "DPD",
        "dhl": "DHL",
        "ups": "UPS",
        "gls": "GLS",
        "poczta": "POCZTA_POLSKA",
        "pocztex": "POCZTA_POLSKA",
        "fedex": "FEDEX",
        "orlen": "ORLEN_PACZKA",
    }
    for keyword, carrier_id in carrier_keywords.items():
        if keyword in name_lower:
            return carrier_id

    logger.warning(
        "Nie rozpoznano przewoznika dla metody dostawy: %s",
        delivery_method_name,
    )
    return "OTHER"
