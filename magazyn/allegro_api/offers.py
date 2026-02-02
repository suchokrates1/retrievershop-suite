"""
Pobieranie ofert z Allegro API.
"""
from typing import Callable, Optional
from decimal import Decimal

import requests

from .core import (
    API_BASE_URL,
    DEFAULT_TIMEOUT,
    _request_with_retry,
    _describe_token,
    _extract_allegro_error_details,
    _safe_int,
    _force_clear_allegro_tokens,
)
from .auth import refresh_token
from ..env_tokens import clear_allegro_tokens, update_allegro_tokens
from ..settings_store import SettingsPersistenceError, settings_store


def fetch_offers(access_token: str, offset: int = 0, limit: int = 100, **kwargs) -> dict:
    """
    Pobierz oferty z Allegro używając access tokenu.

    Parameters
    ----------
    access_token : str
        OAuth access token dla Allegro API.
    offset : int
        Offset od którego rozpocząć pobieranie. Domyślnie 0.
    limit : int
        Liczba wyników na żądanie. Domyślnie 100.
    **kwargs
        Dodatkowe parametry zapytania.

    Returns
    -------
    dict
        Odpowiedź JSON z listą ofert.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    params = {"offset": offset, "limit": limit, **kwargs}
    url = f"{API_BASE_URL}/sale/offers"

    response = _request_with_retry(
        requests.get,
        url,
        endpoint="offers",
        headers=headers,
        params=params,
    )
    return response.json()


def fetch_product_listing(
    ean: str,
    page: int = 1,
    *,
    debug: Optional[Callable[[str, object], None]] = None,
) -> list:
    """
    Pobierz oferty produktu zidentyfikowanego przez EAN.

    Parameters
    ----------
    ean : str
        Kod EAN lub fraza wyszukiwania.
    page : int
        Strona startowa listingu. Domyślnie 1.

    Returns
    -------
    list
        Lista słowników z id, seller i sellingMode.price.amount dla oferty.
    """

    def record(label: str, value: object) -> None:
        if debug is None:
            return
        try:
            debug(label, value)
        except Exception:
            pass

    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")
    record(
        "Listing Allegro: używany access token",
        _describe_token(token),
    )
    record(
        "Listing Allegro: używany refresh token",
        _describe_token(refresh),
    )
    if not token:
        record(
            "Listing Allegro: błąd przed pobraniem",
            "Missing Allegro access token",
        )
        raise RuntimeError("Missing Allegro access token")

    params = {"page": page}
    if ean.isdigit():
        params["ean"] = ean
    else:
        params["phrase"] = ean

    url = f"{API_BASE_URL}/offers/listing"
    offers = []
    refreshed = False

    def handle_listing_http_error(exc) -> bool:
        nonlocal token, refresh, refreshed
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code not in (401, 403):
            return False

        friendly_message = (
            "Failed to refresh Allegro access token for product listing; "
            "please re-authorize the Allegro integration"
        )

        error_payload = {"status_code": status_code}
        error_payload.update(_extract_allegro_error_details(getattr(exc, "response", None)))
        record("Listing Allegro: otrzymano błąd HTTP", error_payload)

        latest_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        latest_refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")
        if latest_token and latest_token != token:
            token = latest_token
            refresh = latest_refresh
            record(
                "Listing Allegro: znaleziono zaktualizowany access token",
                _describe_token(token),
            )
            return True
        if latest_refresh and latest_refresh != refresh:
            refresh = latest_refresh

        if refresh and not refreshed:
            refreshed = True
            record(
                "Listing Allegro: odświeżanie tokenu",
                _describe_token(refresh),
            )
            try:
                token_data = refresh_token(refresh)
            except Exception as refresh_exc:
                clear_allegro_tokens()
                _force_clear_allegro_tokens()
                record(
                    "Listing Allegro: odświeżanie nieudane",
                    str(refresh_exc),
                )
                raise RuntimeError(friendly_message) from refresh_exc

            new_token = token_data.get("access_token")
            if not new_token:
                clear_allegro_tokens()
                _force_clear_allegro_tokens()
                record(
                    "Listing Allegro: brak tokenu po odświeżeniu",
                    token_data,
                )
                raise RuntimeError(friendly_message)

            token = new_token
            new_refresh = token_data.get("refresh_token")
            if new_refresh:
                refresh = new_refresh
            expires_in = _safe_int(token_data.get("expires_in")) if token_data else None
            try:
                update_allegro_tokens(token, refresh, expires_in)
            except SettingsPersistenceError as exc:
                friendly_message = (
                    "Cannot refresh Allegro access token because the settings store is "
                    "read-only; please update the credentials manually"
                )
                record(
                    "Listing Allegro: zapis tokenów nieudany",
                    str(exc),
                )
                raise RuntimeError(friendly_message) from exc
            record(
                "Listing Allegro: odświeżanie zakończone",
                {
                    "access_token": _describe_token(token),
                    "refresh_token": _describe_token(refresh),
                },
            )
            return True

        raise RuntimeError(friendly_message) from exc

    while True:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.allegro.public.v1+json",
        }
        try:
            record(
                "Listing Allegro: pobieranie strony",
                {"page": page},
            )
            response = _request_with_retry(
                requests.get,
                url,
                endpoint="listing",
                headers=headers,
                params=params,
            )
        except Exception as exc:
            if handle_listing_http_error(exc):
                continue
            raise
        try:
            response.raise_for_status()
        except Exception as exc:
            if handle_listing_http_error(exc):
                continue
            raise
        data = response.json()
        record(
            "Listing Allegro: odpowiedź strony",
            {
                "page": page,
                "items": len(data.get("items", {}) or {}),
                "links": list((data.get("links") or {}).keys()),
            },
        )

        items = data.get("items", {})
        page_offers = []
        if isinstance(items, dict):
            for key in ("promoted", "regular", "offers"):
                page_offers.extend(items.get(key, []))
        elif isinstance(items, list):
            page_offers = items

        for offer in page_offers:
            offers.append(
                {
                    "id": offer.get("id"),
                    "seller": offer.get("seller"),
                    "sellingMode": {
                        "price": {
                            "amount": offer.get("sellingMode", {})
                            .get("price", {})
                            .get("amount")
                        }
                    },
                }
            )

        next_link = data.get("links", {}).get("next")
        if not next_link:
            break
        page += 1
        params["page"] = page

    return offers


def get_offer_details(offer_id: str) -> dict:
    """
    Pobiera szczegoly oferty z Allegro (w tym aktualna cene).

    Parameters
    ----------
    offer_id : str
        ID oferty Allegro.

    Returns
    -------
    dict
        Slownik z danymi oferty lub bledem.
    """
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not token:
        return {"success": False, "error": "Brak tokenu Allegro"}
    
    url = f"{API_BASE_URL}/sale/product-offers/{offer_id}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    
    try:
        response = _request_with_retry(
            requests.get,
            url,
            endpoint="get-offer",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        
        # Wyciagnij cene z odpowiedzi
        price = None
        selling_mode = data.get("sellingMode", {})
        if selling_mode:
            price_data = selling_mode.get("price", {})
            if price_data:
                price = Decimal(str(price_data.get("amount", 0)))
        
        return {
            "success": True,
            "price": price,
            "title": data.get("name"),
            "status": data.get("publication", {}).get("status"),
            "data": data
        }
    except requests.exceptions.HTTPError as e:
        error_detail = _extract_allegro_error_details(e.response)
        return {
            "success": False, 
            "error": error_detail.get("message", str(e)),
            "details": error_detail
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_offer_price(offer_id: str) -> dict:
    """
    Pobiera aktualna cene oferty z Allegro API.

    Parameters
    ----------
    offer_id : str
        ID oferty Allegro.

    Returns
    -------
    dict
        Slownik z kluczami: success, price (Decimal), currency, error (jesli blad).
    """
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not token:
        return {"success": False, "error": "Brak tokenu Allegro"}
    
    url = f"{API_BASE_URL}/sale/product-offers/{offer_id}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    
    try:
        response = _request_with_retry(
            requests.get,
            url,
            endpoint="get-offer-price",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        
        price_data = data.get("sellingMode", {}).get("price", {})
        price_amount = price_data.get("amount")
        
        if price_amount is not None:
            return {
                "success": True,
                "price": Decimal(str(price_amount)),
                "currency": price_data.get("currency", "PLN"),
            }
        else:
            return {"success": False, "error": "Brak ceny w odpowiedzi API"}
            
    except requests.exceptions.HTTPError as e:
        error_detail = _extract_allegro_error_details(e.response)
        return {
            "success": False, 
            "error": error_detail.get("message", str(e)),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def change_offer_price(offer_id: str, new_price: Decimal) -> dict:
    """
    Zmienia cene oferty na Allegro.

    Parameters
    ----------
    offer_id : str
        ID oferty Allegro.
    new_price : Decimal
        Nowa cena oferty.

    Returns
    -------
    dict
        Odpowiedz z Allegro API lub slownik z bledem.
    """
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not token:
        return {"success": False, "error": "Brak tokenu Allegro"}
    
    # Allegro API wymaga PATCH na /sale/product-offers/{offerId}
    # z body: {"sellingMode": {"price": {"amount": "123.45", "currency": "PLN"}}}
    url = f"{API_BASE_URL}/sale/product-offers/{offer_id}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
    }
    
    payload = {
        "sellingMode": {
            "price": {
                "amount": str(new_price),
                "currency": "PLN"
            }
        }
    }
    
    try:
        response = _request_with_retry(
            requests.patch,
            url,
            endpoint="change-price",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except requests.exceptions.HTTPError as e:
        error_detail = _extract_allegro_error_details(e.response)
        return {
            "success": False, 
            "error": error_detail.get("message", str(e)),
            "details": error_detail
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
