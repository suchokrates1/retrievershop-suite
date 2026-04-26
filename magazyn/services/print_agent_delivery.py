"""Dobor uslug dostawy Allegro dla agenta drukowania."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional


def get_delivery_method_id(service: Dict[str, Any]) -> Optional[str]:
    """Wyciagnij deliveryMethodId z id uslugi."""
    service_id = service.get("id")
    if isinstance(service_id, dict):
        return service_id.get("deliveryMethodId")
    return service_id


def is_allegro_standard(service: Dict[str, Any]) -> bool:
    """Sprawdz czy usluga to Allegro Standard, czyli bez umowy wlasnej."""
    service_id = service.get("id")
    if isinstance(service_id, dict):
        return not service_id.get("credentialsId")
    return True


def pick_best_delivery_service(
    candidates: List[Dict[str, Any]],
    delivery_method: str,
    logger: logging.Logger,
) -> Optional[str]:
    """Wybierz usluge Allegro Standard, a gdy jej brak pierwsza umowe wlasna."""
    allegro_standard = [service for service in candidates if is_allegro_standard(service)]
    if allegro_standard:
        chosen = allegro_standard[0]
        logger.info(
            "Wybrano usluge Allegro Standard (SMART): %s (id=%s)",
            chosen.get("name"),
            get_delivery_method_id(chosen),
        )
        return get_delivery_method_id(chosen)

    chosen = candidates[0]
    logger.warning(
        "Brak uslugi Allegro Standard dla '%s' - uzywam umowy wlasnej: %s (id=%s, credentialsId=%s)",
        delivery_method,
        chosen.get("name"),
        get_delivery_method_id(chosen),
        (chosen.get("id") or {}).get("credentialsId", "?"),
    )
    return get_delivery_method_id(chosen)


def resolve_delivery_service_id(
    delivery_method: str,
    services: Iterable[Dict[str, Any]],
    logger: logging.Logger,
) -> Optional[str]:
    """Mapuj nazwe metody dostawy Allegro na deliveryMethodId."""
    if not delivery_method:
        return None

    available_services = list(services)
    method_lower = delivery_method.lower()

    exact = [
        service
        for service in available_services
        if (service.get("name") or "").lower() == method_lower
    ]
    if exact:
        return pick_best_delivery_service(exact, delivery_method, logger)

    partial = [
        service
        for service in available_services
        if method_lower in (service.get("name") or "").lower()
        or (service.get("name") or "").lower() in method_lower
    ]
    if partial:
        return pick_best_delivery_service(partial, delivery_method, logger)

    method_keywords = set(method_lower.split())
    keyword_matches = []
    for service in available_services:
        service_name = (service.get("name") or "").lower()
        service_keywords = set(service_name.split())
        common_keywords = method_keywords & service_keywords
        if len(common_keywords) >= 2:
            keyword_matches.append(service)

    if keyword_matches:
        return pick_best_delivery_service(keyword_matches, delivery_method, logger)

    logger.warning(
        "Nie znaleziono delivery_service_id dla '%s' wsrod %d dostepnych uslug: %s",
        delivery_method,
        len(available_services),
        [service.get("name") for service in available_services[:20]],
    )
    return None


__all__ = [
    "get_delivery_method_id",
    "is_allegro_standard",
    "pick_best_delivery_service",
    "resolve_delivery_service_id",
]