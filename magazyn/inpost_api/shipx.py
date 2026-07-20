"""InPost ShipX — tworzenie przesylek i etykiet dla zamowien Woo."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

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


def create_shipment_and_label(
    order_data: dict,
    *,
    wait_seconds: float = 8.0,
) -> dict[str, Any]:
    """Utworz przesylke ShipX i zwroc waybill + PDF bytes."""
    client = InpostShipxClient()
    shipment = client.create_shipment(build_shipment_payload(order_data))
    shipment_id = shipment.get("id")
    if not shipment_id:
        raise InpostShipxError(f"Brak id przesylki w odpowiedzi: {shipment}")

    # Poczekaj na nadanie numeru
    waybill = ""
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        details = client.get_shipment(shipment_id)
        waybill = details.get("tracking_number") or ""
        status = (details.get("status") or "").lower()
        if waybill or status in {"confirmed", "dispatched", "offers_prepared"}:
            if not waybill:
                waybill = str(shipment_id)
            break
        time.sleep(1.0)
    else:
        details = client.get_shipment(shipment_id)
        waybill = details.get("tracking_number") or str(shipment_id)

    label_pdf = client.get_label_pdf(shipment_id)
    return {
        "shipment_id": str(shipment_id),
        "waybill": waybill,
        "label_pdf": label_pdf,
        "carrier_id": "INPOST",
        "courier_code": "INPOST",
        "courier_package_nr": waybill,
    }
