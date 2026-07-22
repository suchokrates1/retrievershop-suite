"""InPost ShipX — tworzenie przesylek i etykiet dla zamowien Woo."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

import requests

from ..settings_store import settings_store

logger = logging.getLogger(__name__)

SHIPX_BASE = "https://api-shipx-pl.easypack24.net"


class InpostShipxError(RuntimeError):
    def __init__(self, message: str, *, payload: Any = None):
        super().__init__(message)
        self.payload = payload


class InpostShipxClient:
    def __init__(
        self,
        token: Optional[str] = None,
        organization_id: Optional[str | int] = None,
        timeout: int = 45,
    ):
        self.token = token or settings_store.get("INPOST_TOKEN") or ""
        org = organization_id or settings_store.get("INPOST_ORGANIZATION_ID") or ""
        self.organization_id = str(org)
        self.timeout = timeout
        if not self.token or not self.organization_id:
            raise InpostShipxError("Brak INPOST_TOKEN lub INPOST_ORGANIZATION_ID")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{SHIPX_BASE}{path}"
        response = requests.request(
            method,
            url,
            headers=self._headers(),
            timeout=self.timeout,
            **kwargs,
        )
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = response.text[:500]
            raise InpostShipxError(
                f"ShipX {method} {path} -> {response.status_code}: {payload}",
                payload=payload,
            )
        if not response.content:
            return None
        return response.json()

    def create_shipment(self, payload: dict) -> dict:
        return self.request(
            "POST",
            f"/v1/organizations/{self.organization_id}/shipments",
            json=payload,
        )

    def calculate_shipments(self, shipments: list[dict]) -> list[dict]:
        """Wylicz ceny przesyłek bez tworzenia (prepaid). Debet często bez ceny."""
        result = self.request(
            "POST",
            f"/v1/organizations/{self.organization_id}/shipments/calculate",
            json={"shipments": shipments},
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("shipments") or result.get("calculations") or [result]
        return []

    def get_shipment(self, shipment_id: str | int) -> dict:
        return self.request("GET", f"/v1/shipments/{shipment_id}")

    def get_label_pdf(self, shipment_id: str | int) -> bytes:
        url = f"{SHIPX_BASE}/v1/shipments/{shipment_id}/label"
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/pdf",
            },
            params={"format": "Pdf", "type": "A6"},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise InpostShipxError(
                f"ShipX label {shipment_id} -> {response.status_code}: {response.text[:300]}"
            )
        return response.content


def _sender_payload() -> dict:
    street = settings_store.get("SENDER_STREET") or "Wroclawska"
    building = settings_store.get("SENDER_BUILDING") or "15/7"
    # Jesli street zawiera numer budynku — rozdziel
    if not settings_store.get("SENDER_BUILDING") and " " in street:
        parts = street.rsplit(" ", 1)
        if parts[-1] and any(ch.isdigit() for ch in parts[-1]):
            street, building = parts[0], parts[1]
    return {
        "company_name": settings_store.get("SENDER_COMPANY") or "Retriever Shop",
        "first_name": (settings_store.get("SENDER_NAME") or "Retriever").split()[0],
        "last_name": " ".join((settings_store.get("SENDER_NAME") or "Shop").split()[1:]) or "Shop",
        "email": settings_store.get("SENDER_EMAIL") or "kontakt@retrievershop.pl",
        "phone": (settings_store.get("SENDER_PHONE") or "605864663").replace(" ", ""),
        "address": {
            "street": street,
            "building_number": building,
            "city": settings_store.get("SENDER_CITY") or "Legnica",
            "post_code": settings_store.get("SENDER_ZIPCODE") or "59-220",
            "country_code": "PL",
        },
    }


def _normalize_pl_phone(raw: str) -> str:
    """ShipX oczekuje 9 cyfr PL (bez +48)."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if digits.startswith("48") and len(digits) >= 11:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = digits[1:]
    return digits or "500000000"


def build_shipment_payload(order_data: dict) -> dict:
    """Zbuduj payload ShipX z danych zamowienia magazynu."""
    point_id = (order_data.get("delivery_point_id") or "").strip()
    delivery_method = (
        order_data.get("delivery_method")
        or order_data.get("shipping")
        or ""
    )
    is_locker = bool(point_id) or "paczkomat" in delivery_method.lower()

    name = (order_data.get("delivery_fullname") or order_data.get("customer") or "Klient").strip()
    parts = name.split(None, 1)
    first = parts[0] if parts else "Klient"
    last = parts[1] if len(parts) > 1 else "."

    receiver: dict[str, Any] = {
        "first_name": first,
        "last_name": last,
        "email": order_data.get("email") or settings_store.get("SENDER_EMAIL"),
        "phone": _normalize_pl_phone(order_data.get("phone") or ""),
    }

    # Konto Woo/InPost ma typowo locker + courier C2C (nie B2B courier_standard)
    service = "inpost_locker_standard" if is_locker else "inpost_courier_c2c"
    # C2C wymaga sending_method (nadanie w paczkomacie / zlecenie odbioru)
    sending_method = (
        settings_store.get("INPOST_SENDING_METHOD") or "parcel_locker"
    ).strip()
    payload: dict[str, Any] = {
        "receiver": receiver,
        "sender": _sender_payload(),
        "parcels": {"template": "small"},
        "service": service,
        "reference": order_data.get("order_id") or "",
        "custom_attributes": {"sending_method": sending_method},
    }

    if is_locker and point_id:
        payload["custom_attributes"]["target_point"] = point_id
    else:
        street = order_data.get("delivery_address") or ""
        building = order_data.get("delivery_building_number") or ""
        if not building and street:
            parts = street.rsplit(" ", 1)
            if len(parts) == 2 and any(ch.isdigit() for ch in parts[1]):
                street, building = parts[0], parts[1]
        receiver["address"] = {
            "street": street,
            "building_number": building or "1",
            "city": order_data.get("delivery_city") or "",
            "post_code": order_data.get("delivery_postcode") or "",
            "country_code": order_data.get("delivery_country_code") or "PL",
        }

    # COD
    cod_flag = str(order_data.get("payment_method_cod") or "").lower() in {"1", "true", "t"}
    if cod_flag:
        amount = order_data.get("payment_done") or 0
        payload["cod"] = {"amount": float(amount), "currency": "PLN"}

    return payload


def _buy_offer_if_needed(client: InpostShipxClient, shipment_id: str | int, details: dict) -> dict:
    """C2C: wykup oferte gdy jeszcze nie bought."""
    offers = details.get("offers") or []
    if not offers:
        return details
    if any((offer.get("status") or "").lower() == "bought" for offer in offers):
        return details
    offer_id = offers[0].get("id")
    if not offer_id:
        return details
    client.request("POST", f"/v1/shipments/{shipment_id}/buy", json={"offer_id": offer_id})
    return client.get_shipment(shipment_id)


def extract_shipment_price(details: dict) -> float | None:
    """Cena z oferty ShipX lub calculated_charge_amount."""
    from ..domain.shop_shipping import extract_rate_from_shipment

    rate = extract_rate_from_shipment(details or {})
    if rate is not None:
        return float(rate)
    for key in ("calculated_charge_amount", "price"):
        if details.get(key) is not None:
            try:
                return float(details[key])
            except (TypeError, ValueError):
                continue
    return None


def try_calculate_shipment_price(order_data: dict) -> float | None:
    """Spróbuj POST /shipments/calculate — None gdy API nie zwraca ceny."""
    try:
        client = InpostShipxClient()
        payload = build_shipment_payload(order_data)
        payload["id"] = order_data.get("order_id") or "calc1"
        rows = client.calculate_shipments([payload])
        if not rows:
            return None
        row = rows[0]
        if row.get("calculated_charge_amount") is not None:
            return float(row["calculated_charge_amount"])
        return extract_shipment_price(row)
    except Exception as exc:
        logger.debug("ShipX calculate niedostępne: %s", exc)
        return None


def create_shipment_and_label(
    order_data: dict,
    *,
    wait_seconds: float = 20.0,
    on_shipment_created: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Utworz przesylke ShipX i zwroc waybill + PDF bytes.

    ``on_shipment_created`` wywolywany zaraz po otrzymaniu id (przed waitem
    na confirmed/label) — pozwala zapisac id i uniknac duplikatow przy retry.
    """
    client = InpostShipxClient()
    shipment = client.create_shipment(build_shipment_payload(order_data))
    shipment_id = shipment.get("id")
    if not shipment_id:
        raise InpostShipxError(f"Brak id przesylki w odpowiedzi: {shipment}")
    if on_shipment_created:
        on_shipment_created(str(shipment_id))

    # C2C / locker: poczekaj na oferte, wykup, potwierdzenie i numer
    waybill = ""
    details: dict[str, Any] = shipment
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        details = client.get_shipment(shipment_id)
        details = _buy_offer_if_needed(client, shipment_id, details)
        waybill = details.get("tracking_number") or ""
        status = (details.get("status") or "").lower()
        if waybill and status in {"confirmed", "dispatched", "dispatched_by_sender"}:
            break
        if status in {"confirmed", "dispatched", "dispatched_by_sender"} and not waybill:
            waybill = str(shipment_id)
            break
        time.sleep(1.0)
    else:
        details = client.get_shipment(shipment_id)
        waybill = details.get("tracking_number") or str(shipment_id)

    # Label bywa dostepny dopiero po confirmed
    label_pdf = b""
    label_deadline = time.time() + 15.0
    last_err: Exception | None = None
    while time.time() < label_deadline:
        try:
            label_pdf = client.get_label_pdf(shipment_id)
            if label_pdf:
                break
        except InpostShipxError as exc:
            last_err = exc
            time.sleep(1.0)
    if not label_pdf:
        raise InpostShipxError(
            f"Brak etykiety ShipX dla {shipment_id}: {last_err or 'empty'}"
        )

    shipping_cost = extract_shipment_price(details)
    if shipping_cost is None:
        shipping_cost = try_calculate_shipment_price(order_data)

    return {
        "shipment_id": str(shipment_id),
        "waybill": waybill,
        "label_pdf": label_pdf,
        "carrier_id": "INPOST",
        "courier_code": "INPOST",
        "courier_package_nr": waybill,
        "shipping_cost": shipping_cost,
        "shipment_details": details,
    }
