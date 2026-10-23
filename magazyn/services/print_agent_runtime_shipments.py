"""Runtime helpers przesylek dla LabelAgent."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from ..domain.order_platform import is_allegro_order
from .print_agent_delivery import resolve_delivery_service_id
from .shipment_waybills import extract_waybills_from_shipment_details

_PENDING_PREFIX = "pending:"
_EXTERNAL_PREFIX = "external:"
_PENDING_TTL = timedelta(seconds=120)


def get_order_packages_from_shipment_management(
    order_id: str,
    *,
    load_state_value: Callable[[str], Optional[str]],
    save_state_value: Callable[[str, Optional[str]], None],
    get_shipment_details: Callable[[str], Dict[str, Any]],
    create_allegro_shipment: Callable[[str, str], List[Dict[str, Any]]],
    logger,
    claim_shipment: Optional[Callable[[str, str], bool]] = None,
    list_order_shipments: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> List[Dict[str, Any]]:
    """Zwroc zapisane albo nowo utworzone przesylki Shipment Management dla zamowienia.

    Drugiej przesylki nie tworzymy, gdy ktoś już ją zakłada albo Allegro
    ma już numer listu dla tego zamówienia.
    """
    checkout_form_id = order_id[len("allegro_"):] if is_allegro_order(order_id) else order_id
    state_key = f"sm_shipment:{order_id}"
    current_time = now or datetime.now
    stored = load_state_value(state_key)

    if stored and not _is_pending(stored) and not _is_external(stored):
        try:
            return [_stored_shipment_payload(stored, order_id, get_shipment_details, logger)]
        except Exception as exc:
            logger.warning(
                "Blad pobierania przesylki SM %s: %s. Usuwam mapping.",
                stored,
                exc,
            )
            save_state_value(state_key, None)
            stored = None

    if _is_external(stored):
        logger.warning(
            "Zamowienie %s ma juz list %s w Allegro, bez id SM - nie tworze drugiej przesylki",
            order_id,
            stored[len(_EXTERNAL_PREFIX):],
        )
        return []

    if _is_pending(stored):
        if _pending_is_fresh(stored, current_time()):
            logger.info("Tworzenie przesylki dla %s juz trwa - pomijam", order_id)
            return []
        save_state_value(state_key, None)

    if claim_shipment is not None and not claim_shipment(
        state_key, f"{_PENDING_PREFIX}{current_time().isoformat(timespec='seconds')}"
    ):
        logger.info("Inny proces tworzy przesylke dla %s - pomijam", order_id)
        return []

    try:
        if list_order_shipments is not None and _allegro_already_has_waybill(
            order_id,
            checkout_form_id,
            state_key,
            list_order_shipments,
            save_state_value,
            logger,
        ):
            return []
        created = create_allegro_shipment(order_id, checkout_form_id)
    except Exception:
        _release_pending(state_key, load_state_value, save_state_value)
        raise

    if not created:
        _release_pending(state_key, load_state_value, save_state_value)
    return created


def _allegro_already_has_waybill(
    order_id: str,
    checkout_form_id: str,
    state_key: str,
    list_order_shipments: Callable[[str], List[Dict[str, Any]]],
    save_state_value: Callable[[str, Optional[str]], None],
    logger,
) -> bool:
    try:
        existing = list_order_shipments(checkout_form_id) or []
    except Exception as exc:
        logger.warning(
            "Nie sprawdzilem przesylek Allegro dla %s: %s - nie tworze nowej",
            order_id,
            exc,
        )
        save_state_value(state_key, None)
        return True

    waybills = [
        str(item.get("waybill")).strip()
        for item in existing
        if str(item.get("waybill") or "").strip()
    ]
    if not waybills:
        logger.info("Brak zapisanego shipment_management_id dla %s - tworze nowa przesylke", order_id)
        return False

    logger.warning(
        "Zamowienie %s ma juz przesylke w Allegro (%s) - nie tworze drugiej",
        order_id,
        ", ".join(waybills),
    )
    save_state_value(state_key, f"{_EXTERNAL_PREFIX}{waybills[0]}")
    return True


def _release_pending(
    state_key: str,
    load_state_value: Callable[[str], Optional[str]],
    save_state_value: Callable[[str, Optional[str]], None],
) -> None:
    current = load_state_value(state_key)
    if _is_pending(current):
        save_state_value(state_key, None)


def _is_pending(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(_PENDING_PREFIX)


def _is_external(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(_EXTERNAL_PREFIX)


def _pending_is_fresh(value: str, now: datetime) -> bool:
    raw = value[len(_PENDING_PREFIX):]
    try:
        started = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if started.tzinfo is not None and now.tzinfo is None:
        now = now.astimezone(started.tzinfo)
    elif started.tzinfo is None and now.tzinfo is not None:
        started = started.replace(tzinfo=now.tzinfo)
    return now - started < _PENDING_TTL


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
    waybills = extract_waybills_from_shipment_details(details)
    waybill = waybills[0] if waybills else ""

    logger.info("Uzyto zapisany shipment_management_id=%s dla %s", stored_shipment_id, order_id)
    return {
        "shipment_id": stored_shipment_id,
        "waybill": waybill,
        "waybills": waybills,
        "carrier_id": carrier,
        "courier_code": carrier,
        "courier_package_nr": waybill,
    }


__all__ = ["get_order_packages_from_shipment_management", "resolve_delivery_service_from_api"]