"""Czyste statusy i mapowania domeny zwrotow."""

from __future__ import annotations

from typing import Optional


RETURN_STATUS_PENDING = "pending"
RETURN_STATUS_IN_TRANSIT = "in_transit"
RETURN_STATUS_DELIVERED = "delivered"
RETURN_STATUS_COMPLETED = "completed"
RETURN_STATUS_CANCELLED = "cancelled"


ALLEGRO_RETURN_STATUS_MAP = {
    "CREATED": RETURN_STATUS_PENDING,
    "WAITING_FOR_PARCEL": RETURN_STATUS_PENDING,
    "PARCEL_IN_TRANSIT": RETURN_STATUS_IN_TRANSIT,
    "PARCEL_DELIVERED": RETURN_STATUS_DELIVERED,
    "DELIVERED": RETURN_STATUS_DELIVERED,
    "ACCEPTED": RETURN_STATUS_DELIVERED,
    "COMMISSION_REFUNDED": RETURN_STATUS_COMPLETED,
    "FINISHED": RETURN_STATUS_COMPLETED,
    "REJECTED": RETURN_STATUS_CANCELLED,
}

CARRIER_TO_ALLEGRO_MAP = {
    "inpost": "INPOST",
    "paczkomat": "INPOST",
    "dpd": "DPD",
    "dhl": "DHL",
    "ups": "UPS",
    "fedex": "FEDEX",
    "gls": "GLS",
    "pocztex": "POCZTA_POLSKA",
    "poczta": "POCZTA_POLSKA",
}


def map_allegro_return_status(allegro_status: str) -> str:
    """Mapuj status Allegro na wewnetrzny status zwrotu."""
    return ALLEGRO_RETURN_STATUS_MAP.get(allegro_status, RETURN_STATUS_PENDING)


def map_carrier_to_allegro(carrier_name: Optional[str]) -> Optional[str]:
    """Mapuj nazwe przewoznika na ID w Allegro API."""
    if not carrier_name:
        return None

    carrier_lower = carrier_name.lower()
    for key, value in CARRIER_TO_ALLEGRO_MAP.items():
        if key in carrier_lower:
            return value

    return "ALLEGRO"


__all__ = [
    "ALLEGRO_RETURN_STATUS_MAP",
    "CARRIER_TO_ALLEGRO_MAP",
    "RETURN_STATUS_PENDING",
    "RETURN_STATUS_IN_TRANSIT",
    "RETURN_STATUS_DELIVERED",
    "RETURN_STATUS_COMPLETED",
    "RETURN_STATUS_CANCELLED",
    "map_allegro_return_status",
    "map_carrier_to_allegro",
]