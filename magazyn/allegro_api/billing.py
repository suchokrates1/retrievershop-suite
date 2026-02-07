"""
Billing Allegro API - wpisy billingowe i podsumowania.
"""
from decimal import Decimal
from typing import Optional

import requests

from .core import API_BASE_URL, _request_with_retry
from .shipping import estimate_allegro_shipping_cost


def fetch_billing_entries(
    access_token: str,
    order_id: Optional[str] = None,
    offer_id: Optional[str] = None,
    type_ids: Optional[list[str]] = None,
    occurred_at_gte: Optional[str] = None,
    occurred_at_lte: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """
    Pobierz wpisy billingowe z Allegro API.
    
    Endpoint: GET /billing/billing-entries
    
    Args:
        access_token: Token dostepu Allegro OAuth
        order_id: UUID zamowienia do filtrowania (opcjonalnie)
        offer_id: ID oferty do filtrowania (opcjonalnie)
        type_ids: Lista typow billingowych do filtrowania, np. ["SUC", "LIS"] (opcjonalnie)
        occurred_at_gte: Data od (ISO 8601), np. "2024-01-01T00:00:00Z" (opcjonalnie)
        occurred_at_lte: Data do (ISO 8601) (opcjonalnie)
        limit: Maksymalna liczba wynikow (domyslnie 100)
    
    Returns:
        dict: Slownik z kluczem "billingEntries" zawierajacy liste wpisow billingowych.
        Kazdy wpis zawiera:
        - id: UUID wpisu
        - occurredAt: Data zdarzenia
        - type: {id, name} - typ oplaty (SUC=prowizja, LIS=wystawienie, itp.)
        - offer: {id, name} - powiazana oferta
        - value: {amount, currency} - kwota oplaty
        - balance: {amount, currency} - saldo po operacji
        - order: {id} - UUID zamowienia (jesli dotyczy)
    
    Typy billingowe (najczestsze):
        SUC - Prowizja od sprzedazy (Success Fee)
        LIS - Oplata za wystawienie (Listing Fee)
        SHI - Koszt wysylki
        PRO - Promocja
        REF - Zwrot
    
    Raises:
        HTTPError: Jesli zadanie API nie powiodlo sie
    
    Example:
        >>> entries = fetch_billing_entries(token, order_id="29738e61-7f6a-11e8-ac45-09db60ede9d6")
        >>> for entry in entries.get("billingEntries", []):
        ...     print(f"{entry['type']['name']}: {entry['value']['amount']} PLN")
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    
    params = {"limit": limit}
    
    if order_id:
        params["order.id"] = order_id
    if offer_id:
        params["offer.id"] = offer_id
    if occurred_at_gte:
        params["occurredAt.gte"] = occurred_at_gte
    if occurred_at_lte:
        params["occurredAt.lte"] = occurred_at_lte
    
    if type_ids:
        params_list = [(k, v) for k, v in params.items()]
        for type_id in type_ids:
            params_list.append(("type.id", type_id))
        params = params_list
    
    url = f"{API_BASE_URL}/billing/billing-entries"
    
    response = _request_with_retry(
        requests.get,
        url,
        endpoint="billing_entries",
        headers=headers,
        params=params,
    )
    
    return response.json()


def fetch_billing_types(access_token: str) -> list:
    """
    Pobierz liste wszystkich typow billingowych z Allegro API.
    
    Endpoint: GET /billing/billing-types
    
    Args:
        access_token: Token dostepu Allegro OAuth
    
    Returns:
        list: Lista slownikow z typami billingowymi, kazdy zawiera:
        - id: Kod typu (np. "SUC", "LIS")
        - description: Opis typu w jezyku polskim
    
    Example:
        >>> types = fetch_billing_types(token)
        >>> for t in types:
        ...     print(f"{t['id']}: {t['description']}")
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Accept-Language": "pl-PL",
    }
    
    url = f"{API_BASE_URL}/billing/billing-types"
    
    response = _request_with_retry(
        requests.get,
        url,
        endpoint="billing_types",
        headers=headers,
    )
    
    return response.json()


# Mapowanie typow billingowych Allegro na kategorie
ORGANIC_COMMISSION_TYPES = {
    "SUC",   # Prowizja od sprzedazy (organiczna)
}

PROMOTED_COMMISSION_TYPES = {
    "FSF",   # Prowizja od sprzedazy oferty wyroznionej
    "BRG",   # Prowizja od sprzedazy w Kampanii (Allegro Ads)
}

# Wszystkie typy prowizji (kompatybilnosc wsteczna)
COMMISSION_TYPES = ORGANIC_COMMISSION_TYPES | PROMOTED_COMMISSION_TYPES

SHIPPING_TYPES = {
    "HLB",   # Oplata za dostawe DHL Allegro Delivery
    "ORB",   # Oplata za dostawe ORLEN Paczka Allegro Delivery
    "DXP",   # Oplata za dostawe One Kurier Allegro Delivery
    "HB4",   # Oplata za dostawe InPost
    "SHI",   # Oplata za wysylke (ogolna)
    "SHIP",  # Wysylka
    "DLV",   # Dostawa
}

PROMO_TYPES = {
    "FEA",   # Oplata za wyroznenie
    "DPG",   # Oplata za promowanie na stronie dzialu
    "PRO",   # Promocja
    "ADS",   # Reklama
}

REFUND_TYPES = {
    "REF",   # Zwrot kosztow
    "CB2",   # Bonus z Kampanii
    "PAD",   # Pobranie oplat z wplywow (dodatnie)
}

LISTING_TYPES = {
    "LIS",   # Oplata za wystawienie
}


def get_order_billing_summary(
    access_token: str, 
    order_id: str,
    delivery_method: Optional[str] = None,
    order_value: Optional[Decimal] = None
) -> dict:
    """
    Pobierz podsumowanie kosztow billingowych dla zamowienia.
    
    Agreguje wszystkie wpisy billingowe dla danego zamowienia i zwraca
    podsumowanie z podzilem na typy oplat. Jesli API nie zwroci kosztu wysylki,
    a podano delivery_method i order_value, szacuje koszt na podstawie tabeli Allegro Smart.
    
    Args:
        access_token: Token dostepu Allegro OAuth
        order_id: UUID zamowienia (format: "29738e61-7f6a-11e8-ac45-09db60ede9d6")
        delivery_method: Opcjonalna nazwa metody dostawy do szacowania
        order_value: Opcjonalna wartosc zamowienia do szacowania
    
    Returns:
        dict: Slownik z podsumowaniem kosztow:
        {
            "success": True/False,
            "commission": Decimal - prowizja od sprzedazy,
            "listing_fee": Decimal - oplata za wystawienie,
            "shipping_fee": Decimal - koszty wysylki,
            "promo_fee": Decimal - oplaty promocyjne,
            "other_fees": Decimal - pozostale oplaty,
            "total_fees": Decimal - suma wszystkich oplat,
            "refunds": Decimal - zwroty (wartosci dodatnie),
            "entries": list - surowe wpisy billingowe,
            "fee_details": list - szczegoly oplat z nazwami,
            "error": str - komunikat bledu (jesli success=False)
        }
    
    Example:
        >>> summary = get_order_billing_summary(token, "29738e61-7f6a-11e8-ac45-09db60ede9d6")
        >>> if summary["success"]:
        ...     print(f"Prowizja: {summary['commission']} PLN")
        ...     print(f"Suma oplat: {summary['total_fees']} PLN")
    """
    result = {
        "success": False,
        "commission": Decimal("0"),
        "promoted_commission": Decimal("0"),
        "is_promoted_sale": False,
        "promotion_type": None,
        "listing_fee": Decimal("0"),
        "shipping_fee": Decimal("0"),
        "promo_fee": Decimal("0"),
        "other_fees": Decimal("0"),
        "total_fees": Decimal("0"),
        "refunds": Decimal("0"),
        "entries": [],
        "fee_details": [],
        "error": None,
    }
    
    try:
        data = fetch_billing_entries(access_token, order_id=order_id)
        entries = data.get("billingEntries", [])
        result["entries"] = entries
        
        for entry in entries:
            type_info = entry.get("type", {})
            type_id = type_info.get("id", "")
            type_name = type_info.get("name", type_id)
            value = entry.get("value", {})
            amount_str = value.get("amount", "0")
            
            try:
                amount = Decimal(amount_str)
            except Exception:
                amount = Decimal("0")
            
            if amount < 0:
                result["fee_details"].append({
                    "type_id": type_id,
                    "name": type_name,
                    "amount": abs(amount),
                })
            
            if type_id in PROMOTED_COMMISSION_TYPES:
                fee = abs(amount) if amount < 0 else Decimal("0")
                result["commission"] += fee
                result["promoted_commission"] += fee
                result["is_promoted_sale"] = True
                if type_id == "FSF":
                    result["promotion_type"] = "wyroznione"
                elif type_id == "BRG" and result["promotion_type"] != "wyroznione":
                    result["promotion_type"] = "allegro_ads"
            elif type_id in ORGANIC_COMMISSION_TYPES:
                result["commission"] += abs(amount) if amount < 0 else Decimal("0")
            elif type_id in LISTING_TYPES:
                result["listing_fee"] += abs(amount) if amount < 0 else Decimal("0")
            elif type_id in SHIPPING_TYPES:
                if amount < 0:
                    result["shipping_fee"] += abs(amount)
                else:
                    result["refunds"] += amount
            elif type_id in PROMO_TYPES:
                result["promo_fee"] += abs(amount) if amount < 0 else Decimal("0")
            elif type_id in REFUND_TYPES:
                if amount > 0:
                    result["refunds"] += amount
            else:
                if amount < 0:
                    result["other_fees"] += abs(amount)
                    result["fee_details"].append({
                        "type_id": type_id,
                        "name": type_name,
                        "amount": abs(amount),
                    })
        
        result["total_fees"] = (
            result["commission"] +
            result["listing_fee"] +
            result["shipping_fee"] +
            result["promo_fee"] +
            result["other_fees"]
        )
        
        result["success"] = True
        
    except Exception as e:
        result["error"] = str(e)
    
    if result["shipping_fee"] == Decimal("0") and delivery_method and order_value:
        estimate = estimate_allegro_shipping_cost(delivery_method, order_value)
        result["estimated_shipping"] = estimate
        result["shipping_fee_estimated"] = estimate["estimated_cost"]
        result["fee_details"].append({
            "type_id": "EST",
            "name": f"Szacowany koszt wysylki ({estimate['delivery_method_matched']})",
            "amount": estimate["estimated_cost"],
            "is_estimate": True,
        })
        result["total_fees_with_estimate"] = result["total_fees"] + estimate["estimated_cost"]
    else:
        result["estimated_shipping"] = None
        result["shipping_fee_estimated"] = None
        result["total_fees_with_estimate"] = result["total_fees"]
    
    return result
