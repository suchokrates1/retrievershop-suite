"""
Polling dziennika zdarzen Allegro (Order Events API).

Endpoint: GET /order/events
Dokumentacja: https://developer.allegro.pl/tutorials/jak-obslugiwac-zamowienia-GRaj0qyvwtR#dziennik-zdarzen

Mechanizm event-driven polling:
- Inkrementalne pobieranie zmian (parametr from={last_seen_event_id})
- Typy zdarzen: BOUGHT, FILLED_IN, READY_FOR_PROCESSING, BUYER_CANCELLED,
  FULFILLMENT_STATUS_CHANGED, AUTO_CANCELLED
- Limit: 1-1000 zdarzen na request (domyslnie 100)
- Allegro zaleca events jako glowny mechanizm monitorowania zamowien
"""
import logging
from typing import Optional

import requests

from .core import (
    API_BASE_URL,
    _request_with_retry,
    _extract_allegro_error_details,
)
from .orders import _get_allegro_token, _refresh_allegro_token

logger = logging.getLogger(__name__)

# Typy zdarzen, ktore nas interesuja
ACTIONABLE_EVENT_TYPES = frozenset({
    "READY_FOR_PROCESSING",
    "BUYER_CANCELLED",
    "AUTO_CANCELLED",
    "FULFILLMENT_STATUS_CHANGED",
})


def fetch_order_events(
    *,
    from_event_id: Optional[str] = None,
    event_types: Optional[list[str]] = None,
    limit: int = 1000,
) -> dict:
    """
    Pobierz zdarzenia zamowien z Allegro.

    GET /order/events

    Parameters
    ----------
    from_event_id : str, optional
        ID ostatniego przetworzonego zdarzenia (inkrementalne).
        Jesli None, zwraca najnowsze zdarzenia.
    event_types : list[str], optional
        Filtr typow zdarzen. Jesli None, zwraca wszystkie typy.
    limit : int
        Liczba zdarzen na strone (1-1000). Domyslnie 1000.

    Returns
    -------
    dict
        Odpowiedz JSON z kluczem 'events' (lista zdarzen).
        Kazde zdarzenie zawiera: id, type, occurredAt, order (checkoutForm.id).
    """
    token, refresh = _get_allegro_token()
    url = f"{API_BASE_URL}/order/events"

    params = {"limit": min(max(limit, 1), 1000)}
    if from_event_id:
        params["from"] = from_event_id
    if event_types:
        params["type"] = event_types

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }

    refreshed = False
    while True:
        try:
            response = _request_with_retry(
                requests.get,
                url,
                endpoint="order-events",
                headers=headers,
                params=params,
            )
            return response.json()
        except Exception as exc:
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                logger.info("Token Allegro wygasl, odswiezam (events)...")
                new_token = _refresh_allegro_token(refresh)
                headers["Authorization"] = f"Bearer {new_token}"
                continue
            details = _extract_allegro_error_details(
                getattr(exc, "response", None)
            )
            logger.error(
                "Blad pobierania zdarzen Allegro: %s %s",
                exc,
                details,
            )
            raise


def fetch_event_stats() -> dict:
    """
    Pobierz statystyki zdarzen (najnowsze zdarzenie).

    GET /order/event-stats

    Zwraca info o najnowszym zdarzeniu - przydatne do inicjalizacji
    kursora przy pierwszym uruchomieniu.

    Returns
    -------
    dict
        Odpowiedz JSON z kluczem 'latestEvent' (id, occurredAt).
    """
    token, refresh = _get_allegro_token()
    url = f"{API_BASE_URL}/order/event-stats"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }

    refreshed = False
    while True:
        try:
            response = _request_with_retry(
                requests.get,
                url,
                endpoint="order-event-stats",
                headers=headers,
            )
            return response.json()
        except Exception as exc:
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                logger.info("Token Allegro wygasl, odswiezam (event-stats)...")
                new_token = _refresh_allegro_token(refresh)
                headers["Authorization"] = f"Bearer {new_token}"
                continue
            details = _extract_allegro_error_details(
                getattr(exc, "response", None)
            )
            logger.error(
                "Blad pobierania statystyk zdarzen Allegro: %s %s",
                exc,
                details,
            )
            raise
