"""
Pobieranie zamowien z Allegro REST API.

Endpoint: GET /order/checkout-forms
Dokumentacja: https://developer.allegro.pl/tutorials/jak-obslugiwac-zamowienia-GRaj0qyvwtR

Ograniczenia API:
- max 100 zamowien na request (limit)
- offset + limit <= 10 000
- zwraca zamowienia z ostatnich 12 miesiecy
- paginacja przez offset/limit
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from .core import (
    API_BASE_URL,
    _request_with_retry,
    _describe_token,
    _extract_allegro_error_details,
    _force_clear_allegro_tokens,
)
from .auth import refresh_token as _do_refresh_token
from ..env_tokens import clear_allegro_tokens, update_allegro_tokens
from ..settings_store import SettingsPersistenceError, settings_store

logger = logging.getLogger(__name__)

# Mapowanie statusow Allegro na wewnetrzne statusy
ALLEGRO_STATUS_MAP = {
    "BOUGHT": "pobrano",
    "FILLED_IN": "pobrano",
    "READY_FOR_PROCESSING": "wydrukowano",
    "CANCELLED": "anulowano",
}

ALLEGRO_FULFILLMENT_MAP = {
    "NEW": "pobrano",
    "PROCESSING": "wydrukowano",
    "READY_FOR_SHIPMENT": "spakowano",
    "SENT": "w_drodze",
    "PICKED_UP": "dostarczono",
    "CANCELLED": "anulowano",
}


def _get_allegro_token() -> tuple[str, str]:
    """Pobierz aktualny token Allegro z settings_store."""
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")
    if not token:
        raise RuntimeError("Brak tokenu Allegro - wymagana autoryzacja")
    return token, refresh


def _refresh_allegro_token(current_refresh: str) -> str:
    """Odswież token i zwroc nowy access token."""
    try:
        token_data = _do_refresh_token(current_refresh)
    except Exception as exc:
        clear_allegro_tokens()
        _force_clear_allegro_tokens()
        raise RuntimeError(
            "Nie udalo sie odswiezyc tokenu Allegro - wymagana ponowna autoryzacja"
        ) from exc

    new_token = token_data.get("access_token")
    if not new_token:
        clear_allegro_tokens()
        _force_clear_allegro_tokens()
        raise RuntimeError("Brak tokenu po odswiezeniu - wymagana ponowna autoryzacja")

    new_refresh = token_data.get("refresh_token") or current_refresh
    expires_in = token_data.get("expires_in")
    try:
        update_allegro_tokens(new_token, new_refresh, expires_in)
    except SettingsPersistenceError:
        logger.warning("Nie udalo sie zapisac odswiezonego tokenu do settings_store")

    return new_token


def fetch_allegro_orders(
    *,
    limit: int = 100,
    offset: int = 0,
    status: Optional[list[str]] = None,
    fulfillment_status: Optional[list[str]] = None,
    bought_after: Optional[str] = None,
    bought_before: Optional[str] = None,
    updated_after: Optional[str] = None,
    updated_before: Optional[str] = None,
) -> dict:
    """
    Pobierz liste zamowien z Allegro REST API.

    GET /order/checkout-forms

    Parameters
    ----------
    limit : int
        Liczba zamowien na strone (1-100). Domyslnie 100.
    offset : int
        Offset paginacji. offset + limit <= 10000.
    status : list[str], optional
        Filtr statusow zamowienia (BOUGHT, FILLED_IN, READY_FOR_PROCESSING, CANCELLED).
    fulfillment_status : list[str], optional
        Filtr statusow realizacji (NEW, PROCESSING, READY_FOR_SHIPMENT, SENT, PICKED_UP, CANCELLED).
    bought_after : str, optional
        Data minimalna zakupu (ISO 8601).
    bought_before : str, optional
        Data maksymalna zakupu (ISO 8601).
    updated_after : str, optional
        Data minimalna aktualizacji (ISO 8601).
    updated_before : str, optional
        Data maksymalna aktualizacji (ISO 8601).

    Returns
    -------
    dict
        Odpowiedz JSON z kluczami: checkoutForms, count, totalCount.
    """
    token, refresh = _get_allegro_token()
    url = f"{API_BASE_URL}/order/checkout-forms"

    params = {
        "limit": min(max(limit, 1), 100),
        "offset": offset,
    }

    # Filtry statusow (moga byc wielokrotne)
    if status:
        params["status"] = status
    if fulfillment_status:
        params["fulfillment.status"] = fulfillment_status

    # Filtry dat
    if bought_after:
        params["lineItems.boughtAt.gte"] = bought_after
    if bought_before:
        params["lineItems.boughtAt.lte"] = bought_before
    if updated_after:
        params["updatedAt.gte"] = updated_after
    if updated_before:
        params["updatedAt.lte"] = updated_before

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
                endpoint="checkout-forms",
                headers=headers,
                params=params,
            )
            return response.json()
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                logger.info("Token Allegro wygasl, odswiezam...")
                token = _refresh_allegro_token(refresh)
                headers["Authorization"] = f"Bearer {token}"
                continue
            raise


def fetch_allegro_order_detail(order_id: str) -> dict:
    """
    Pobierz szczegoly pojedynczego zamowienia z Allegro.

    GET /order/checkout-forms/{id}

    Parameters
    ----------
    order_id : str
        UUID zamowienia Allegro (checkout-form ID).

    Returns
    -------
    dict
        Pelne dane zamowienia.
    """
    token, refresh = _get_allegro_token()
    url = f"{API_BASE_URL}/order/checkout-forms/{order_id}"

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
                endpoint="checkout-form-detail",
                headers=headers,
            )
            return response.json()
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                token = _refresh_allegro_token(refresh)
                headers["Authorization"] = f"Bearer {token}"
                continue
            raise


def fetch_all_allegro_orders(
    *,
    bought_after: Optional[str] = None,
    bought_before: Optional[str] = None,
    progress_callback=None,
) -> list[dict]:
    """
    Pobierz WSZYSTKIE zamowienia z Allegro (z paginacja).

    Allegro zwraca max 12 miesiecy historii.
    Paginacja: offset/limit, offset + limit <= 10000.

    Parameters
    ----------
    bought_after : str, optional
        Data minimalna zakupu ISO 8601.
    bought_before : str, optional
        Data maksymalna zakupu ISO 8601.
    progress_callback : callable, optional
        Callback(fetched_count, total_count) do raportowania postepu.

    Returns
    -------
    list[dict]
        Lista zamowien (checkout forms).
    """
    all_orders = []
    offset = 0
    limit = 100
    total_count = None

    while True:
        # Sprawdz limit paginacji API (offset + limit <= 10000)
        if offset + limit > 10000:
            logger.warning(
                "Osiagnieto limit paginacji Allegro (offset=%d). "
                "Pobrano %d z %s zamowien.",
                offset, len(all_orders), total_count or "?"
            )
            break

        logger.info(
            "Pobieranie zamowien z Allegro: offset=%d, limit=%d", offset, limit
        )
        data = fetch_allegro_orders(
            limit=limit,
            offset=offset,
            bought_after=bought_after,
            bought_before=bought_before,
        )

        checkout_forms = data.get("checkoutForms", [])
        if total_count is None:
            total_count = data.get("totalCount", 0)
            logger.info("Allegro: laczna liczba zamowien = %d", total_count)

        if not checkout_forms:
            break

        all_orders.extend(checkout_forms)

        if progress_callback:
            try:
                progress_callback(len(all_orders), total_count)
            except Exception:
                pass

        # Sprawdz czy sa kolejne strony
        if len(checkout_forms) < limit:
            break

        offset += limit

    logger.info("Pobrano laczne %d zamowien z Allegro API", len(all_orders))
    return all_orders


def parse_allegro_order_to_data(checkout_form: dict) -> dict:
    """
    Konwertuj dane zamowienia z formatu Allegro API na format kompatybilny
    z sync_order_from_data().

    Parameters
    ----------
    checkout_form : dict
        Pojedynczy checkout form z Allegro API.

    Returns
    -------
    dict
        Dane zamowienia w formacie wewnetrznym.
    """
    cf_id = checkout_form.get("id", "")
    buyer = checkout_form.get("buyer", {})
    delivery = checkout_form.get("delivery", {})
    delivery_address = delivery.get("address", {})
    delivery_method = delivery.get("method", {})
    pickup_point = delivery.get("pickupPoint", {})
    pickup_address = pickup_point.get("address", {}) if pickup_point else {}
    payment = checkout_form.get("payment", {})
    invoice = checkout_form.get("invoice", {})
    invoice_address = invoice.get("address", {}) if invoice else {}
    summary = checkout_form.get("summary", {})
    fulfillment = checkout_form.get("fulfillment", {})
    line_items = checkout_form.get("lineItems", [])

    # Konwersja daty ISO 8601 na Unix timestamp
    def iso_to_unix(iso_str):
        if not iso_str:
            return None
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except (ValueError, TypeError):
            return None

    # Data zakupu - najwczesniejsza data z lineItems
    bought_at_timestamps = []
    for item in line_items:
        ts = iso_to_unix(item.get("boughtAt"))
        if ts:
            bought_at_timestamps.append(ts)
    date_add = min(bought_at_timestamps) if bought_at_timestamps else None

    # Data potwierdzenia platnosci
    date_confirmed = iso_to_unix(payment.get("finishedAt"))

    # Ustaw status wewnetrzny na podstawie fulfillment.status
    fulfillment_status = fulfillment.get("status", "")
    allegro_status = checkout_form.get("status", "")

    # Kwota platnosci
    paid_amount = None
    if payment.get("paidAmount"):
        try:
            paid_amount = float(payment["paidAmount"].get("amount", 0))
        except (ValueError, TypeError):
            pass

    # Koszt dostawy
    delivery_price = None
    delivery_cost = delivery.get("cost", {})
    if delivery_cost:
        try:
            delivery_price = float(delivery_cost.get("amount", 0))
        except (ValueError, TypeError):
            pass

    # Nazwa klienta
    first_name = delivery_address.get("firstName", "")
    last_name = delivery_address.get("lastName", "")
    customer_name = f"{first_name} {last_name}".strip()

    # Invoice
    invoice_company_data = invoice_address.get("company", {}) if invoice_address else {}
    want_invoice = invoice.get("required", False) if invoice else False

    # Produkty - konwersja lineItems na format wewnetrzny
    products = []
    for item in line_items:
        offer = item.get("offer", {})
        external_data = offer.get("external", {})
        price_data = item.get("price", {})

        product = {
            "name": offer.get("name", ""),
            "quantity": item.get("quantity", 1),
            "price_brutto": price_data.get("amount"),
            "auction_id": offer.get("id"),
            "sku": external_data.get("id"),
            "ean": item.get("ean") or "",
            "variant_id": "",
            "product_id": "",
            "order_product_id": None,
            "attributes": "",
            "location": "",
        }

        # Wyciagnij atrybuty (rozmiar, kolor, wariant)
        selected_additional = item.get("selectedAdditionalServices", [])
        product["attributes"] = ""

        products.append(product)

    # Metoda platnosci
    payment_type = payment.get("type", "")
    payment_method_map = {
        "ONLINE": "Przelew online",
        "CASH_ON_DELIVERY": "Pobranie",
        "INSTALLMENTS": "Raty",
        "SPLIT_PAYMENT": "Platnosc podzielona",
    }
    payment_method = payment_method_map.get(payment_type, payment_type)

    return {
        # ID: uzyj "allegro_{uuid}" jako order_id (aby nie kolidowac z BaseLinker)
        "order_id": f"allegro_{cf_id}",
        "external_order_id": cf_id,
        "shop_order_id": None,
        # Dane klienta
        "customer": customer_name,
        "email": buyer.get("email", ""),
        "phone": delivery_address.get("phoneNumber", ""),
        "user_login": buyer.get("login", ""),
        # Zrodlo
        "platform": "allegro",
        "order_source_id": None,
        "order_status_id": None,
        "confirmed": allegro_status == "READY_FOR_PROCESSING",
        # Daty
        "date_add": date_add,
        "date_confirmed": date_confirmed,
        "date_in_status": None,
        # Dostawa
        "shipping": delivery_method.get("name", ""),
        "delivery_method": delivery_method.get("name", ""),
        "delivery_method_id": None,
        "delivery_price": delivery_price,
        "delivery_fullname": customer_name,
        "delivery_company": delivery_address.get("companyName", ""),
        "delivery_address": delivery_address.get("street", ""),
        "delivery_city": delivery_address.get("city", ""),
        "delivery_postcode": delivery_address.get("zipCode", ""),
        "delivery_country": "",
        "delivery_country_code": delivery_address.get("countryCode", "PL"),
        # Punkt odbioru
        "delivery_point_id": pickup_point.get("id", "") if pickup_point else "",
        "delivery_point_name": pickup_point.get("name", "") if pickup_point else "",
        "delivery_point_address": pickup_address.get("street", ""),
        "delivery_point_postcode": pickup_address.get("zipCode", ""),
        "delivery_point_city": pickup_address.get("city", ""),
        # Faktura
        "invoice_fullname": "",
        "invoice_company": invoice_company_data.get("name", "") if isinstance(invoice_company_data, dict) else "",
        "invoice_nip": invoice_company_data.get("taxId", "") if isinstance(invoice_company_data, dict) else "",
        "invoice_address": invoice_address.get("street", "") if invoice_address else "",
        "invoice_city": invoice_address.get("city", "") if invoice_address else "",
        "invoice_postcode": invoice_address.get("zipCode", "") if invoice_address else "",
        "invoice_country": "",
        "want_invoice": want_invoice,
        # Platnosc
        "currency": summary.get("totalToPay", {}).get("currency", "PLN"),
        "payment_method": payment_method,
        "payment_method_cod": payment_type == "CASH_ON_DELIVERY",
        "payment_done": paid_amount,
        # Komentarze
        "user_comments": checkout_form.get("messageToSeller", ""),
        "admin_comments": "",
        # Kurier
        "courier_code": "",
        "delivery_package_module": delivery_method.get("name", ""),
        "delivery_package_nr": "",
        # Produkty
        "products": products,
        # Metadane Allegro (do ustalenia statusu)
        "_allegro_status": allegro_status,
        "_allegro_fulfillment_status": fulfillment_status,
    }


def get_allegro_internal_status(order_data: dict) -> str:
    """
    Okresl wewnetrzny status na podstawie danych Allegro.

    Parameters
    ----------
    order_data : dict
        Dane zamowienia (z parse_allegro_order_to_data).

    Returns
    -------
    str
        Wewnetrzny status zamowienia.
    """
    fulfillment = order_data.get("_allegro_fulfillment_status", "")
    allegro_status = order_data.get("_allegro_status", "")

    # Fulfillment status ma priorytet
    if fulfillment:
        internal = ALLEGRO_FULFILLMENT_MAP.get(fulfillment)
        if internal:
            return internal

    # Fallback na status zamowienia
    return ALLEGRO_STATUS_MAP.get(allegro_status, "pobrano")
