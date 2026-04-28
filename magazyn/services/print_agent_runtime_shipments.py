"""Runtime helpers przesylek dla LabelAgent."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .print_agent_delivery import resolve_delivery_service_id


def get_order_packages_from_shipment_management(
    order_id: str,
    *,
    load_state_value: Callable[[str], Optional[str]],
    save_state_value: Callable[[str, Optional[str]], None],
    get_shipment_details: Callable[[str], Dict[str, Any]],
    create_allegro_shipment: Callable[[str, str], List[Dict[str, Any]]],
    logger,
) -> List[Dict[str, Any]]:
    """Zwroc zapisane albo nowo utworzone przesylki Shipment Management dla zamowienia."""
    checkout_form_id = order_id[len("allegro_"):] if order_id.startswith("allegro_") else order_id
    state_key = f"sm_shipment:{order_id}"

    stored_shipment_id = load_state_value(state_key)
    if stored_shipment_id:
        try:
            return [_stored_shipment_payload(stored_shipment_id, order_id, get_shipment_details, logger)]
        except Exception as exc:
            logger.warning(
                "Blad pobierania przesylki SM %s: %s. Usuwam mapping.",
                stored_shipment_id,
                exc,
            )
            save_state_value(state_key, None)

    logger.info("Brak zapisanego shipment_management_id dla %s - tworze nowa przesylke", order_id)
    return create_allegro_shipment(order_id, checkout_form_id)


def resolve_delivery_service_from_api(delivery_method: str, *, get_delivery_services, logger) -> Optional[str]:
    """Pobierz uslugi dostawy Allegro i wybierz najlepszy deliveryMethodId."""
    if not delivery_method:
        return None
    try:
        services = get_delivery_services()
    except Exception as exc:
        logger.error("Blad pobierania delivery services: %s", exc)
        return None
    return resolve_delivery_service_id(delivery_method, services, logger)


def _stored_shipment_payload(stored_shipment_id: str, order_id: str, get_shipment_details, logger) -> dict:
    details = get_shipment_details(stored_shipment_id)
    carrier = details.get("carrier", "")
    waybill = ""
    for package in details.get("packages", []):
        waybill = package.get("waybill", "")
        if waybill:
            break

    logger.info("Uzyto zapisany shipment_management_id=%s dla %s", stored_shipment_id, order_id)
    return {
        "shipment_id": stored_shipment_id,
        "waybill": waybill,
        "carrier_id": carrier,
        "courier_code": carrier,
        "courier_package_nr": waybill,
    }


__all__ = ["get_order_packages_from_shipment_management", "resolve_delivery_service_from_api"]