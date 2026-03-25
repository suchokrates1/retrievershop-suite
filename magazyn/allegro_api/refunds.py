"""
Modul oblugi zwrotow pieniedzy przez Allegro API.

Umozliwia:
- Pobieranie szczegolowych danych zwrotu
- Inicjowanie zwrotu pieniedzy przez POST /payments/refunds
- Walidacje i potwierdzenie operacji zwrotu
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

from .core import API_BASE_URL, DEFAULT_TIMEOUT, _request_with_retry

logger = logging.getLogger(__name__)


# Statusy Allegro Customer Return
ALLEGRO_RETURN_STATUS_DELIVERED = "DELIVERED"
ALLEGRO_RETURN_STATUS_ACCEPTED = "ACCEPTED"
ALLEGRO_RETURN_STATUS_COMMISSION_REFUNDED = "COMMISSION_REFUNDED"
ALLEGRO_RETURN_STATUS_FINISHED = "FINISHED"

# Statusy pozwalajace na zwrot pieniedzy
REFUNDABLE_STATUSES = {
    ALLEGRO_RETURN_STATUS_DELIVERED,
    "PARCEL_DELIVERED",
    ALLEGRO_RETURN_STATUS_ACCEPTED,
}


def get_customer_return(access_token: str, return_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Pobierz szczegoly zwrotu klienta z Allegro API.
    
    Args:
        access_token: Token dostepu Allegro
        return_id: ID zwrotu w Allegro (customerReturnId)
    
    Returns:
        Tuple (dane_zwrotu, blad) - jesli blad to None, dane_zwrotu zawiera odpowiedz API
    """
    if not access_token:
        return None, "Brak tokenu dostepu Allegro"
    
    if not return_id:
        return None, "Brak ID zwrotu Allegro"
    
    url = f"{API_BASE_URL}/order/customer-returns/{return_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
    }
    
    try:
        response = _request_with_retry(
            requests.get,
            url,
            endpoint="customer-returns",
            headers=headers,
            timeout=DEFAULT_TIMEOUT
        )
        
        if response.status_code == 200:
            return response.json(), None
        elif response.status_code == 404:
            return None, f"Zwrot o ID {return_id} nie istnieje w Allegro"
        elif response.status_code == 401:
            return None, "Brak autoryzacji - sprawdz token Allegro"
        else:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get("error_description", error_data.get("message", response.text))
            return None, f"Blad Allegro API ({response.status_code}): {error_msg}"
            
    except requests.RequestException as e:
        logger.error(f"Blad HTTP przy pobieraniu zwrotu {return_id}: {e}")
        return None, f"Blad polaczenia z Allegro: {str(e)}"
    except Exception as e:
        logger.error(f"Nieoczekiwany blad przy pobieraniu zwrotu {return_id}: {e}")
        return None, f"Nieoczekiwany blad: {str(e)}"


def validate_return_for_refund(return_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Sprawdz czy zwrot kwalifikuje sie do zwrotu pieniedzy.
    
    Args:
        return_data: Dane zwrotu z Allegro API
    
    Returns:
        Tuple (czy_mozna_zwrocic, komunikat)
    """
    if not return_data:
        return False, "Brak danych zwrotu"
    
    status = return_data.get("status")
    
    if status in {ALLEGRO_RETURN_STATUS_COMMISSION_REFUNDED, ALLEGRO_RETURN_STATUS_FINISHED}:
        return False, f"Zwrot juz zostal rozliczony (status: {status})"
    
    if status not in REFUNDABLE_STATUSES:
        return False, f"Zwrot nie kwalifikuje sie do zwrotu pieniedzy (status: {status}). Wymagany status: DELIVERED lub ACCEPTED"
    
    # Oblicz kwote do zwrotu - z totalValue lub z items
    refund = return_data.get("refund") or {}
    total_value = refund.get("totalValue") or {}
    amount = float(total_value.get("amount", 0))
    currency = total_value.get("currency", "PLN")
    
    if amount <= 0:
        # Oblicz z items jesli brak totalValue
        items = return_data.get("items", [])
        for item in items:
            price = item.get("price", {})
            item_amount = float(price.get("amount", 0))
            qty = int(item.get("quantity", 1))
            amount += item_amount * qty
            if not currency or currency == "PLN":
                currency = price.get("currency", "PLN")
    
    if amount <= 0:
        return False, "Brak kwoty do zwrotu"
    
    return True, f"Zwrot gotowy do realizacji: {amount:.2f} {currency}"


def get_checkout_form(access_token: str, order_external_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Pobierz dane checkout-form (platnosc, line items) z Allegro API.
    """
    url = f"{API_BASE_URL}/order/checkout-forms/{order_external_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    try:
        response = _request_with_retry(
            requests.get, url, endpoint="checkout-forms",
            headers=headers, timeout=DEFAULT_TIMEOUT
        )
        if response.status_code == 200:
            return response.json(), None
        return None, f"Blad pobierania checkout-form ({response.status_code}): {response.text[:200]}"
    except requests.RequestException as e:
        return None, f"Blad polaczenia: {e}"


def initiate_refund(
    access_token: str,
    return_id: str,
    order_external_id: str,
    line_items: Optional[List[Dict[str, Any]]] = None,
    delivery_cost_covered: bool = True,
    reason: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Inicjuj zwrot pieniedzy przez POST /payments/refunds.

    Args:
        access_token: Token dostepu Allegro
        return_id: ID zwrotu w Allegro (customerReturnId) - do walidacji statusu
        order_external_id: external_order_id zamowienia (UUID z checkout-forms)
        line_items: Lista pozycji do zwrotu [{id, type, quantity}].
                    Jesli None, pobiera z checkout-forms i zwraca wszystkie.
        delivery_cost_covered: Czy zwrocic koszt dostawy
        reason: Opcjonalny powod

    Returns:
        Tuple (sukces, komunikat, dane_odpowiedzi)
    """
    if not access_token:
        return False, "Brak tokenu dostepu Allegro", None

    if not return_id:
        return False, "Brak ID zwrotu Allegro", None

    if not order_external_id:
        return False, "Brak external_order_id zamowienia", None

    # Waliduj status zwrotu
    return_data, error = get_customer_return(access_token, return_id)
    if error:
        return False, error, None

    can_refund, validation_msg = validate_return_for_refund(return_data)
    if not can_refund:
        return False, validation_msg, None

    # Pobierz dane platnosci z checkout-forms
    checkout_data, cf_error = get_checkout_form(access_token, order_external_id)
    if cf_error:
        return False, f"Blad pobierania danych platnosci: {cf_error}", None

    payment = checkout_data.get("payment", {})
    payment_id = payment.get("id")
    if not payment_id:
        return False, "Brak payment.id w danych zamowienia", None

    # Jesli brak line_items - zwroc wszystkie pozycje z checkout-forms
    if not line_items:
        cf_items = checkout_data.get("lineItems", [])
        if not cf_items:
            return False, "Brak pozycji w zamowieniu", None
        line_items = [
            {"id": item["id"], "type": "QUANTITY", "quantity": item.get("quantity", 1)}
            for item in cf_items
        ]

    command_id = str(uuid.uuid4())
    payload = {
        "payment": {"id": payment_id},
        "order": {"id": order_external_id},
        "commandId": command_id,
        "reason": reason or "REFUND",
        "lineItems": line_items,
    }

    url = f"{API_BASE_URL}/payments/refunds"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
    }

    try:
        logger.info(
            "Inicjuje zwrot pieniedzy: return_id=%s, order=%s, payment=%s, command=%s",
            return_id, order_external_id, payment_id, command_id,
        )
        response = _request_with_retry(
            requests.post, url, endpoint="payments-refunds",
            headers=headers, json=payload, timeout=DEFAULT_TIMEOUT,
        )

        if response.status_code in (200, 201):
            resp_data = response.json()
            total = resp_data.get("totalValue", {})
            amount = total.get("amount", "?")
            currency = total.get("currency", "PLN")
            logger.info(
                "Zwrot pieniedzy zainicjowany: return_id=%s, kwota=%s %s, refund_id=%s",
                return_id, amount, currency, resp_data.get("id"),
            )
            return True, f"Zwrot pieniedzy zainicjowany! Kwota: {amount} {currency}", resp_data

        # Obslog bledow
        error_data = {}
        try:
            error_data = response.json()
        except Exception:
            pass

        errors = error_data.get("errors", [])
        error_msg = "; ".join(e.get("message", str(e)) for e in errors) if errors else error_data.get("message", response.text[:300])

        if response.status_code == 422:
            return False, f"Blad walidacji: {error_msg}", None
        elif response.status_code == 401:
            return False, "Brak autoryzacji - sprawdz token Allegro", None
        elif response.status_code == 403:
            return False, "Brak uprawnien do wykonania zwrotu", None
        else:
            logger.error("Blad Allegro API (%s): %s", response.status_code, error_msg)
            return False, f"Blad Allegro API ({response.status_code}): {error_msg}", None

    except requests.RequestException as e:
        logger.error("Blad HTTP przy inicjowaniu zwrotu %s: %s", return_id, e)
        return False, f"Blad polaczenia z Allegro: {e}", None


def get_refund_status(access_token: str, return_id: str) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """
    Sprawdz status zwrotu pieniedzy.
    
    Args:
        access_token: Token dostepu Allegro
        return_id: ID zwrotu w Allegro
    
    Returns:
        Tuple (status, dane_refundu, blad)
    """
    return_data, error = get_customer_return(access_token, return_id)
    if error:
        return None, None, error
    
    status = return_data.get("status")
    refund = return_data.get("refund", {})
    
    return status, refund, None
