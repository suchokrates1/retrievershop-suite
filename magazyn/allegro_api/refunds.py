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

from .core import API_BASE_URL, DEFAULT_TIMEOUT, _extract_allegro_error_details, _request_with_retry

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

ALLEGRO_REFUND_REASON_REFUND = "REFUND"
ALLEGRO_REFUND_REASONS = {ALLEGRO_REFUND_REASON_REFUND}


def _normalize_refund_reason(reason: Optional[str]) -> str:
    """Zwróć dozwolony kod reason dla Allegro payments/refunds."""
    normalized = (reason or "").strip().upper()
    if normalized in ALLEGRO_REFUND_REASONS:
        return normalized
    return ALLEGRO_REFUND_REASON_REFUND


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


def _normalize_offer_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_item_name(value: Any) -> str:
    return str(value or "").strip().lower()


def build_refund_line_items(
    return_items: List[Dict[str, Any]],
    checkout_data: Dict[str, Any],
) -> Tuple[Optional[List[Dict[str, Any]]], float, str, Optional[str]]:
    """
    Mapuj zwracane pozycje na payload lineItems dla POST /payments/refunds.

    Dopasowanie: offerId -> offer.id z checkout-form, fallback po nazwie produktu.
    """
    if not return_items:
        return None, 0.0, "PLN", None

    checkout_lines = checkout_data.get("lineItems") or []
    if not checkout_lines:
        return None, 0.0, "PLN", "Brak pozycji w checkout-form"

    by_offer: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}
    for line in checkout_lines:
        offer_id = _normalize_offer_id((line.get("offer") or {}).get("id"))
        name = _normalize_item_name((line.get("offer") or {}).get("name"))
        if offer_id:
            by_offer[offer_id] = line
        if name:
            by_name[name] = line

    payload: List[Dict[str, Any]] = []
    total_amount = 0.0
    currency = "PLN"

    for return_item in return_items:
        offer_id = _normalize_offer_id(
            return_item.get("offerId")
            or return_item.get("offer_id")
            or return_item.get("auction_id")
        )
        name = _normalize_item_name(return_item.get("name"))
        quantity = int(return_item.get("quantity", 1) or 1)

        checkout_line = by_offer.get(offer_id) if offer_id else None
        if checkout_line is None and name:
            checkout_line = by_name.get(name)
        if checkout_line is None:
            label = return_item.get("name") or offer_id or "nieznana pozycja"
            return None, 0.0, currency, f"Nie znaleziono pozycji checkout dla zwrotu: {label}"

        ordered_qty = int(checkout_line.get("quantity", 1) or 1)
        refund_qty = min(max(quantity, 1), ordered_qty)
        payload.append(
            {
                "id": checkout_line["id"],
                "type": "QUANTITY",
                "quantity": refund_qty,
            }
        )

        price = return_item.get("price") or checkout_line.get("price") or {}
        amount = float(price.get("amount", 0) or 0)
        currency = price.get("currency", currency) or currency
        total_amount += amount * refund_qty

    return payload, total_amount, currency, None


def build_partial_refund_details(
    return_items: List[Dict[str, Any]],
    checkout_data: Dict[str, Any],
    *,
    delivery_cost_covered: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Wylicz kwote i pozycje zwrotu na podstawie faktycznie zwracanych produktow."""
    line_items, total_amount, currency, error = build_refund_line_items(return_items, checkout_data)
    if error:
        return None, error
    if not line_items:
        return None, "Brak pozycji do zwrotu"

    delivery = checkout_data.get("delivery") or {}
    delivery_cost = delivery.get("cost") or {}
    delivery_amount = float(delivery_cost.get("amount", 0) or 0)
    order_line_count = len(checkout_data.get("lineItems") or [])
    is_partial = len(return_items) < order_line_count

    if delivery_cost_covered and delivery_amount > 0:
        total_amount += delivery_amount

    returned_items = [
        {
            "name": item.get("name"),
            "quantity": int(item.get("quantity", 1) or 1),
            "offer_id": item.get("offerId") or item.get("offer_id") or item.get("auction_id"),
        }
        for item in return_items
    ]

    return {
        "total_amount": total_amount,
        "delivery_amount": delivery_amount,
        "currency": currency,
        "line_items": line_items,
        "is_partial": is_partial,
        "returned_items": returned_items,
        "items": returned_items,
    }, None


def build_checkout_refund_details(checkout_data: Dict[str, Any]) -> Dict[str, Any]:
    """Wylicz szczegoly refundu bez Customer Returns API."""
    payment = checkout_data.get("payment") or {}
    summary = checkout_data.get("summary") or {}
    delivery = checkout_data.get("delivery") or {}

    total_to_pay = summary.get("totalToPay") or payment.get("paidAmount") or {}
    delivery_cost = delivery.get("cost") or {}

    total_amount = float(total_to_pay.get("amount", 0) or 0)
    delivery_amount = float(delivery_cost.get("amount", 0) or 0)
    currency = (
        total_to_pay.get("currency")
        or delivery_cost.get("currency")
        or "PLN"
    )

    if total_amount <= 0:
        for item in checkout_data.get("lineItems") or []:
            price = (item.get("price") or {}).get("amount")
            if price is None:
                continue
            total_amount += float(price) * int(item.get("quantity", 1) or 1)

    return {
        "total_amount": total_amount,
        "delivery_amount": delivery_amount,
        "currency": currency,
        "items": checkout_data.get("lineItems") or [],
    }


def initiate_refund(
    access_token: str,
    return_id: Optional[str],
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

    if not order_external_id:
        return False, "Brak external_order_id zamowienia", None

    if return_id:
        # Waliduj status zwrotu tylko dla Customer Returns
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
        "reason": _normalize_refund_reason(reason),
        "lineItems": line_items,
    }

    if delivery_cost_covered:
        delivery = checkout_data.get("delivery") or {}
        delivery_cost = delivery.get("cost") or {}
        delivery_amount = delivery_cost.get("amount")
        if delivery_amount and float(delivery_amount) > 0:
            payload["delivery"] = {
                "value": {
                    "amount": str(delivery_amount),
                    "currency": delivery_cost.get("currency", "PLN"),
                }
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
            return_id or "<synthetic>", order_external_id, payment_id, command_id,
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
                return_id or "<synthetic>", amount, currency, resp_data.get("id"),
            )
            return True, f"Zwrot pieniedzy zainicjowany! Kwota: {amount} {currency}", resp_data

        # Obslog bledow
        error_data = {}
        try:
            error_data = response.json()
        except ValueError as exc:
            logger.debug("Nie udało się zdekodować błędu zwrotu Allegro jako JSON: %s", exc)

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

    except requests.HTTPError as e:
        error_details = _extract_allegro_error_details(getattr(e, "response", None))
        error_message = error_details.get("error_message") or str(e)
        logger.error(
            "Blad HTTP przy inicjowaniu zwrotu %s: %s details=%s",
            return_id or "<synthetic>",
            error_message,
            error_details,
        )
        return False, f"Blad polaczenia z Allegro: {error_message}", None
    except requests.RequestException as e:
        logger.error("Blad HTTP przy inicjowaniu zwrotu %s: %s", return_id or "<synthetic>", e)
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
