"""
Serwis etykiet - tworzenie przesylek i pobieranie etykiet z Allegro API.

Flow:
1. Pobierz delivery_services (cachowane)
2. Dopasuj delivery_service_id na podstawie delivery_method zamowienia
3. Utworz shipment (POST /shipment-management/shipments)
4. Pobierz szczegoly przesylki (status, waybill)
5. Pobierz etykiete (GET .../label)
6. Zapisz waybill i shipment_id do zamowienia
"""

import logging
import time
from typing import Optional

from ..allegro_api.shipment_management import (
    create_shipment,
    get_delivery_services,
    get_shipment_details,
    get_shipment_label,
    cancel_shipment,
)
from ..allegro_api.carriers import resolve_carrier_id
from ..allegro_api.fulfillment import (
    add_shipment_tracking,
    update_fulfillment_status,
)
from ..settings_store import settings_store

logger = logging.getLogger(__name__)

# Statusy przesylki z Shipment Management API
SHIPMENT_CONFIRMED = "CONFIRMED"
SHIPMENT_CANCELLED = "CANCELLED"

# Maksymalny czas oczekiwania na potwierdzenie przesylki
_MAX_WAIT_SECONDS = 30
_POLL_INTERVAL = 2


def _load_sender_data() -> dict:
    """Zaladuj dane nadawcy z settings_store."""
    return {
        "name": settings_store.get("SENDER_NAME") or "Retriever Shop",
        "street": settings_store.get("SENDER_STREET") or "",
        "city": settings_store.get("SENDER_CITY") or "",
        "zipCode": settings_store.get("SENDER_ZIPCODE") or "",
        "countryCode": settings_store.get("SENDER_COUNTRY_CODE") or "PL",
        "phone": settings_store.get("SENDER_PHONE") or "",
        "email": settings_store.get("SENDER_EMAIL") or "",
    }


def _build_receiver(order_data: dict) -> dict:
    """Zbuduj dane odbiorcy na podstawie zamowienia."""
    delivery = order_data.get("delivery", {})
    address = delivery.get("address", {})
    pickup_point = delivery.get("pickupPoint", {})

    receiver = {
        "name": (address.get("firstName", "") + " "
                 + address.get("lastName", "")).strip(),
        "street": address.get("street", ""),
        "city": address.get("city", ""),
        "zipCode": address.get("zipCode", ""),
        "countryCode": address.get("countryCode", "PL"),
        "phone": address.get("phoneNumber")
                 or order_data.get("buyer", {}).get("phoneNumber", ""),
        "email": order_data.get("buyer", {}).get("email", ""),
    }

    if pickup_point and pickup_point.get("id"):
        receiver["pickupPointId"] = pickup_point["id"]

    return receiver


def _find_delivery_service_id(delivery_method_name: str) -> Optional[str]:
    """Znajdz delivery_service_id na podstawie nazwy metody dostawy.

    Przeszukuje liste dostepnych uslug dostawy z API i dopasowuje
    po nazwie.
    """
    if not delivery_method_name:
        return None

    services = get_delivery_services()
    name_lower = delivery_method_name.lower().strip()

    # Proba dokladnego dopasowania
    for svc in services:
        svc_name = (svc.get("name") or "").lower()
        if svc_name == name_lower:
            return svc.get("id")

    # Proba czesciowego dopasowania
    for svc in services:
        svc_name = (svc.get("name") or "").lower()
        if name_lower in svc_name or svc_name in name_lower:
            return svc.get("id")

    logger.warning(
        "Nie znaleziono uslugi dostawy dla: %s (dostepne: %s)",
        delivery_method_name,
        [s.get("name") for s in services[:5]],
    )
    return None


def _default_packages(total_qty: int = 1) -> list[dict]:
    """Domyslna paczka dla zamowienia. Gabaryt A do 5 szt, B powyzej."""
    if total_qty > 5:
        dims = {"length": 40, "width": 30, "height": 20}
    else:
        dims = {"length": 30, "width": 20, "height": 10}
    return [{
        "weight": {"value": 1.0, "unit": "KILOGRAM"},
        "dimensions": {
            "length": dims["length"],
            "width": dims["width"],
            "height": dims["height"],
            "unit": "CENTIMETER",
        },
    }]


def _wait_for_confirmation(shipment_id: str) -> dict:
    """Czekaj az przesylka zostanie potwierdzona.

    Polluje co _POLL_INTERVAL sekund az status != DRAFT
    lub minie _MAX_WAIT_SECONDS.

    Returns
    -------
    dict
        Szczegoly potwierdzonej przesylki.

    Raises
    ------
    RuntimeError
        Gdy przesylka nie zostala potwierdzona w czasie.
    """
    elapsed = 0.0
    while elapsed < _MAX_WAIT_SECONDS:
        details = get_shipment_details(shipment_id)
        status = details.get("status", "")
        if status != "DRAFT":
            if status == SHIPMENT_CANCELLED:
                raise RuntimeError(
                    f"Przesylka {shipment_id} zostala anulowana przez Allegro"
                )
            return details
        time.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL

    raise RuntimeError(
        f"Przesylka {shipment_id} nie zostala potwierdzona w ciagu "
        f"{_MAX_WAIT_SECONDS}s"
    )


class AllegroLabelService:
    """Serwis do tworzenia przesylek i pobierania etykiet z Allegro."""

    def create_and_get_label(
        self,
        *,
        checkout_form_id: str,
        order_data: dict,
        packages: Optional[list[dict]] = None,
        label_format: str = "PDF",
    ) -> dict:
        """Utworz przesylke i pobierz etykiete.

        Parameters
        ----------
        checkout_form_id : str
            UUID zamowienia Allegro.
        order_data : dict
            Surowe dane zamowienia z Allegro API (checkout-form).
        packages : list[dict], optional
            Specyfikacja paczek. Domyslnie standardowa paczka.
        label_format : str
            Format etykiety: "PDF" lub "ZPL".

        Returns
        -------
        dict
            Klucze: shipment_id, waybill, carrier_id, label_data (bytes),
            label_format, status.
        """
        delivery = order_data.get("delivery", {})
        delivery_method = delivery.get("method", {})
        method_name = delivery_method.get("name", "")

        # 1. Znajdz delivery_service_id
        delivery_service_id = _find_delivery_service_id(method_name)
        if not delivery_service_id:
            raise RuntimeError(
                f"Nie znaleziono uslugi dostawy dla metody: {method_name}"
            )

        # 2. Przygotuj dane
        sender = _load_sender_data()
        receiver = _build_receiver(order_data)

        # Oblicz ilosc produktow do wyboru gabarytu
        line_items = order_data.get("lineItems", [])
        total_qty = sum(li.get("quantity", 1) for li in line_items) if line_items else 1
        pkgs = packages or _default_packages(total_qty)

        # 3. Utworz przesylke
        shipment = create_shipment(
            checkout_form_id=checkout_form_id,
            delivery_service_id=delivery_service_id,
            sender=sender,
            receiver=receiver,
            packages=pkgs,
        )
        shipment_id = shipment["id"]

        # 4. Czekaj na potwierdzenie
        details = _wait_for_confirmation(shipment_id)
        waybill = None
        for pkg in details.get("packages", []):
            if pkg.get("waybill"):
                waybill = pkg["waybill"]
                break

        # 5. Pobierz etykiete
        label_data = get_shipment_label(shipment_id, label_format=label_format)

        # 6. Rozpoznaj przewoznika
        carrier_id = resolve_carrier_id(method_name)

        result = {
            "shipment_id": shipment_id,
            "waybill": waybill,
            "carrier_id": carrier_id,
            "label_data": label_data,
            "label_format": label_format.upper(),
            "status": details.get("status", "CONFIRMED"),
        }

        logger.info(
            "Etykieta gotowa: przesylka=%s, waybill=%s, przewoznik=%s",
            shipment_id, waybill, carrier_id,
        )
        return result

    def register_tracking(
        self,
        *,
        checkout_form_id: str,
        carrier_id: str,
        waybill: str,
    ) -> dict:
        """Dodaj numer przesylki do zamowienia Allegro i zmien status.

        Parameters
        ----------
        checkout_form_id : str
            UUID zamowienia Allegro.
        carrier_id : str
            ID przewoznika (INPOST, DPD itp.).
        waybill : str
            Numer listu przewozowego.

        Returns
        -------
        dict
            Odpowiedz z Allegro.
        """
        result = add_shipment_tracking(
            checkout_form_id,
            carrier_id=carrier_id,
            waybill=waybill,
        )
        logger.info(
            "Zarejestrowano tracking %s/%s dla zamowienia %s",
            carrier_id, waybill, checkout_form_id,
        )
        return result

    def cancel(self, shipment_id: str) -> dict:
        """Anuluj przesylke.

        Parameters
        ----------
        shipment_id : str
            ID przesylki z create_and_get_label().

        Returns
        -------
        dict
            Wynik anulowania.
        """
        return cancel_shipment([shipment_id])
