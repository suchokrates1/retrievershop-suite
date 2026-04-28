"""Integracje zewnetrzne runtime agenta etykiet."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..allegro_api import fetch_allegro_order_detail
from ..settings_store import settings_store
from .print_agent_errors import ApiError, PrintError
from .print_agent_labels import CollectedLabels, PrintLabelService
from .print_agent_orders import collect_printable_orders
from .print_agent_runtime_shipments import (
    get_order_packages_from_shipment_management,
    resolve_delivery_service_from_api,
)
from .print_agent_shipment_creation import PrintShipmentCreator
from .print_agent_shipments import resolve_carrier_id
from .printing import PrintCommandError


def maybe_log_api_summary(agent) -> None:
    now = datetime.now()
    if now - agent._last_api_log >= timedelta(hours=1) and agent._api_calls_total:
        agent.logger.info(
            "Udane połączenia: [%s/%s]",
            agent._api_calls_success,
            agent._api_calls_total,
        )
        agent._api_calls_total = 0
        agent._api_calls_success = 0
        agent._last_api_log = now


def get_orders(agent) -> List[Dict[str, Any]]:
    try:
        return collect_printable_orders(log=agent.logger)
    except Exception as exc:
        agent.logger.error("Blad pobierania zamowien z bazy: %s", exc)
        raise ApiError(str(exc)) from exc


def get_order_packages(agent, order_id: str, *, get_shipment_details, create_allegro_shipment):
    return get_order_packages_from_shipment_management(
        order_id,
        load_state_value=agent._load_state_value,
        save_state_value=agent._save_state_value,
        get_shipment_details=get_shipment_details,
        create_allegro_shipment=create_allegro_shipment,
        logger=agent.logger,
    )


def create_allegro_shipment(agent, order_id: str, checkout_form_id: str) -> List[Dict[str, Any]]:
    return shipment_creator(agent).create(order_id, checkout_form_id, agent.last_order_data)


def shipment_creator(
    agent,
    *,
    create_shipment,
    wait_for_shipment_creation,
    get_shipment_details,
    add_shipment_tracking,
    update_fulfillment_status,
) -> PrintShipmentCreator:
    return PrintShipmentCreator(
        logger=agent.logger,
        settings_store=settings_store,
        fetch_order_detail=fetch_allegro_order_detail,
        resolve_delivery_service_id=agent._resolve_delivery_service_id,
        resolve_carrier_id=agent._resolve_carrier_id,
        create_shipment=create_shipment,
        wait_for_shipment_creation=wait_for_shipment_creation,
        get_shipment_details=get_shipment_details,
        add_shipment_tracking=add_shipment_tracking,
        update_fulfillment_status=update_fulfillment_status,
        save_state_value=agent._save_state_value,
    )


def resolve_delivery_service_id(agent, delivery_method: str, *, get_delivery_services) -> Optional[str]:
    return resolve_delivery_service_from_api(
        delivery_method,
        get_delivery_services=get_delivery_services,
        logger=agent.logger,
    )


def label_service(
    agent,
    *,
    get_shipment_label,
    cancel_shipment,
    create_shipment,
    label_errors_total,
) -> PrintLabelService:
    return PrintLabelService(
        logger=agent.logger,
        get_shipment_label=get_shipment_label,
        cancel_shipment=cancel_shipment,
        create_shipment=lambda order_id, checkout_form_id: create_shipment(
            order_id,
            checkout_form_id,
        ),
        fetch_label=lambda courier_code, package_id: agent.get_label(courier_code, package_id),
        recreate_shipment_and_get_label=(
            lambda order_id, old_shipment_id, courier_code, package_ids, tracking_numbers:
            agent._recreate_shipment_and_get_label(
                order_id,
                old_shipment_id,
                courier_code,
                package_ids,
                tracking_numbers,
            )
        ),
        retry=agent._retry,
        errors_total=label_errors_total,
    )


def collect_order_labels(agent, order_id: str, packages: List[Dict[str, Any]]) -> CollectedLabels:
    return agent._label_service().collect_order_labels(order_id, packages)


def recreate_shipment_and_get_label(
    agent,
    order_id: str,
    old_shipment_id: str,
    courier_code: str,
    package_ids: List[str],
    tracking_numbers: List[str],
) -> Tuple[str, str]:
    return agent._label_service().recreate_shipment_and_get_label(
        order_id,
        old_shipment_id,
        courier_code,
        package_ids,
        tracking_numbers,
    )


def get_label(agent, courier_code: str, package_id: str) -> Tuple[str, str]:
    return agent._label_service().get_label(courier_code, package_id)


def print_label(agent, base64_data: str, extension: str, order_id: str, *, labels_total, errors_total) -> None:
    try:
        agent.printer.print_label_base64(base64_data, extension)
        agent.logger.info("Label printed")
        labels_total.inc()
    except PrintCommandError as exc:
        errors_total.labels(stage="print").inc()
        raise PrintError(str(exc)) from exc
    except PrintError:
        raise
    except Exception as exc:
        agent.logger.error("Błąd drukowania: %s", exc)
        errors_total.labels(stage="print").inc()
        raise PrintError(str(exc)) from exc


def print_test_page(agent) -> bool:
    try:
        agent.printer.print_text("=== TEST PRINT ===\n")
        agent.logger.info("Testowa strona została wysłana do drukarki.")
        return True
    except Exception as exc:
        agent.logger.error("Błąd testowego druku: %s", exc)
        return False


__all__ = [
    "collect_order_labels",
    "create_allegro_shipment",
    "get_label",
    "get_order_packages",
    "get_orders",
    "label_service",
    "maybe_log_api_summary",
    "print_label",
    "print_test_page",
    "recreate_shipment_and_get_label",
    "resolve_carrier_id",
    "resolve_delivery_service_id",
    "shipment_creator",
]