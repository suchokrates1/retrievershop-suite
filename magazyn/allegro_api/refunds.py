"""
Modul oblugi zwrotow pieniedzy przez Allegro API.

Umozliwia:
- Pobieranie szczegolowych danych zwrotu
- Inicjowanie zwrotu pieniedzy dla zwrotu w statusie PARCEL_DELIVERED
- Walidacje i potwierdzenie operacji zwrotu
"""

import logging
from typing import Any, Dict, Optional, Tuple

import requests

from .core import API_BASE_URL, DEFAULT_TIMEOUT, request_with_retry

logger = logging.getLogger(__name__)


# Statusy Allegro Customer Return
ALLEGRO_RETURN_STATUS_DELIVERED = "PARCEL_DELIVERED"
ALLEGRO_RETURN_STATUS_ACCEPTED = "ACCEPTED"
ALLEGRO_RETURN_STATUS_COMMISSION_REFUNDED = "COMMISSION_REFUNDED"
ALLEGRO_RETURN_STATUS_FINISHED = "FINISHED"

# Statusy pozwalajace na zwrot pieniedzy
REFUNDABLE_STATUSES = {
    ALLEGRO_RETURN_STATUS_DELIVERED,
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
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    
    try:
        response = request_with_retry("GET", url, headers=headers, timeout=DEFAULT_TIMEOUT)
        
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
        return False, f"Zwrot nie kwalifikuje sie do zwrotu pieniedzy (status: {status}). Wymagany status: PARCEL_DELIVERED lub ACCEPTED"
    
    # Sprawdz czy jest kwota do zwrotu
    refund = return_data.get("refund", {})
    total_value = refund.get("totalValue", {})
    amount = float(total_value.get("amount", 0))
    
    if amount <= 0:
        return False, "Brak kwoty do zwrotu"
    
    return True, f"Zwrot gotowy do realizacji: {amount} {total_value.get('currency', 'PLN')}"


def initiate_refund(
    access_token: str, 
    return_id: str,
    delivery_cost_covered: bool = True,
    reason: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Inicjuj zwrot pieniedzy dla zwrotu klienta.
    
    Allegro API endpoint: POST /order/customer-returns/{returnId}/refund
    
    UWAGA: Ta operacja jest NIEODWRACALNA! Upewnij sie ze:
    1. Paczka zwrotna zostala odebrana i sprawdzona
    2. Produkty sa w stanie pozwalajacym na zwrot
    3. Uzytkownik potwierdzi operacje
    
    Args:
        access_token: Token dostepu Allegro
        return_id: ID zwrotu w Allegro
        delivery_cost_covered: Czy zwrocic rowniez koszt dostawy (domyslnie True)
        reason: Opcjonalny komentarz do zwrotu
    
    Returns:
        Tuple (sukces, komunikat, dane_odpowiedzi)
    """
    if not access_token:
        return False, "Brak tokenu dostepu Allegro", None
    
    if not return_id:
        return False, "Brak ID zwrotu Allegro", None
    
    # Najpierw pobierz dane zwrotu i zwaliduj
    return_data, error = get_customer_return(access_token, return_id)
    if error:
        return False, error, None
    
    can_refund, validation_msg = validate_return_for_refund(return_data)
    if not can_refund:
        return False, validation_msg, None
    
    # Przygotuj payload dla refundu
    url = f"{API_BASE_URL}/order/customer-returns/{return_id}/refund"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
    }
    
    # Payload - wg dokumentacji Allegro
    payload = {
        "deliveryCostCovered": delivery_cost_covered,
    }
    
    if reason:
        payload["sellerComment"] = reason[:500]  # Max 500 znakow
    
    try:
        logger.info(f"Inicjuje zwrot pieniedzy dla return_id={return_id}")
        response = request_with_retry("POST", url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        
        if response.status_code in (200, 201, 204):
            # Pobierz zaktualizowane dane zwrotu
            updated_data, _ = get_customer_return(access_token, return_id)
            
            refund_info = return_data.get("refund", {})
            total_value = refund_info.get("totalValue", {})
            amount = total_value.get("amount", "?")
            currency = total_value.get("currency", "PLN")
            
            logger.info(f"Zwrot pieniedzy zainicjowany pomyslnie: {return_id}, kwota: {amount} {currency}")
            return True, f"Zwrot pieniedzy zainicjowany pomyslnie! Kwota: {amount} {currency}", updated_data
        
        elif response.status_code == 400:
            error_data = response.json() if response.content else {}
            errors = error_data.get("errors", [])
            if errors:
                error_msg = "; ".join([e.get("message", str(e)) for e in errors])
            else:
                error_msg = error_data.get("message", "Nieprawidlowe zadanie")
            return False, f"Blad walidacji Allegro: {error_msg}", None
        
        elif response.status_code == 401:
            return False, "Brak autoryzacji - sprawdz token Allegro", None
        
        elif response.status_code == 403:
            return False, "Brak uprawnien do wykonania zwrotu dla tego zamowienia", None
        
        elif response.status_code == 404:
            return False, f"Zwrot o ID {return_id} nie istnieje w Allegro", None
        
        elif response.status_code == 409:
            error_data = response.json() if response.content else {}
            return False, f"Konflikt - zwrot mogl zostac juz przetworzony: {error_data.get('message', '')}", None
        
        else:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get("message", response.text)
            logger.error(f"Nieoczekiwany blad Allegro API ({response.status_code}): {error_msg}")
            return False, f"Blad Allegro API ({response.status_code}): {error_msg}", None
            
    except requests.RequestException as e:
        logger.error(f"Blad HTTP przy inicjowaniu zwrotu {return_id}: {e}")
        return False, f"Blad polaczenia z Allegro: {str(e)}", None
    except Exception as e:
        logger.error(f"Nieoczekiwany blad przy inicjowaniu zwrotu {return_id}: {e}")
        return False, f"Nieoczekiwany blad: {str(e)}", None


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
