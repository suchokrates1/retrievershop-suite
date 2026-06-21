"""Ekstrakcja numerów przesyłek z odpowiedzi Allegro Shipment Management."""

from __future__ import annotations


def waybills_from_package(package: dict) -> list[str]:
    """Zwróć numery z paczki SM (waybill Allegro + carrierWaybill)."""
    result: list[str] = []
    primary = package.get("waybill")
    if primary:
        result.append(str(primary).strip())
    for info in package.get("transportingInfo") or []:
        carrier_waybill = info.get("carrierWaybill")
        if carrier_waybill:
            value = str(carrier_waybill).strip()
            if value and value not in result:
                result.append(value)
    return result


def expand_carrier_waybill_variants(waybill: str, carrier_id: str | None = None) -> list[str]:
    """Zwróć numer przewoźnika bez syntetycznych wariantów JJD.

    DHL nadaje osobny license plate (JJD...) niezależny od 11-cyfrowego waybill.
    Kody JJD/routing z PDF pobieramy tylko dla Automat DHL BOX 24/7 (label_barcode_extract).
    """
    waybill = str(waybill or "").strip()
    return [waybill] if waybill else []


def extract_waybills_from_shipment_details(details: dict) -> list[str]:
    """Zbierz wszystkie numery z odpowiedzi GET /shipment-management/shipments/{id}."""
    seen: list[str] = []

    def add(raw: str | None, carrier_id: str | None = None) -> None:
        for candidate in expand_carrier_waybill_variants(str(raw or ""), carrier_id):
            if candidate and candidate not in seen:
                seen.append(candidate)

    for package in details.get("packages") or []:
        primary = package.get("waybill")
        if primary:
            add(str(primary))
        for info in package.get("transportingInfo") or []:
            carrier_waybill = info.get("carrierWaybill")
            if carrier_waybill:
                add(str(carrier_waybill), info.get("carrierId"))

    props = details.get("additionalProperties") or {}
    external = props.get("EXTERNAL_CARRIER_WAYBILL")
    if external:
        add(str(external), props.get("FIRST_MILE_CARRIER"))

    return seen


__all__ = [
    "expand_carrier_waybill_variants",
    "extract_waybills_from_shipment_details",
    "waybills_from_package",
]
