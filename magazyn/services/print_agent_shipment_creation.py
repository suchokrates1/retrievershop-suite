"""Tworzenie przesylek Allegro Shipment Management dla agenta drukowania."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .print_agent_shipments import (
    build_additional_services,
    build_cod_payload,
    build_packages,
    build_receiver,
    build_sender,
)


class PrintShipmentCreator:
    """Buduje payload i tworzy shipment w Allegro Shipment Management."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        settings_store: Any,
        fetch_order_detail: Callable[[str], Dict[str, Any]],
        resolve_delivery_service_id: Callable[[str], Optional[str]],
        resolve_carrier_id: Callable[[str], Optional[str]],
        create_shipment: Callable[..., Dict[str, Any]],
        wait_for_shipment_creation: Callable[[str], Dict[str, Any]],
        get_shipment_details: Callable[[str], Dict[str, Any]],
        add_shipment_tracking: Callable[..., Any],
        update_fulfillment_status: Callable[[str, str], Any],
        save_state_value: Callable[[str, Optional[str]], None],
    ):
        self.logger = logger
        self.settings_store = settings_store
        self.fetch_order_detail = fetch_order_detail
        self.resolve_delivery_service_id = resolve_delivery_service_id
        self.resolve_carrier_id = resolve_carrier_id
        self.create_shipment = create_shipment
        self.wait_for_shipment_creation = wait_for_shipment_creation
        self.get_shipment_details = get_shipment_details
        self.add_shipment_tracking = add_shipment_tracking
        self.update_fulfillment_status = update_fulfillment_status
        self.save_state_value = save_state_value

    def create(
        self,
        order_id: str,
        checkout_form_id: str,
        order_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not order_data or order_data.get("order_id") != order_id:
            self.logger.error("Brak danych zamowienia %s do utworzenia przesylki", order_id)
            return []

        delivery_method = order_data.get("delivery_method", "") or order_data.get("shipping", "")
        delivery_method_id, delivery_method = self._resolve_delivery_method(
            order_id,
            checkout_form_id,
            delivery_method,
        )
        if not delivery_method_id:
            self.logger.error(
                "Nie mozna ustalic delivery_method_id dla metody '%s' (zamowienie %s)",
                delivery_method,
                order_id,
            )
            return []

        carrier_id = self.resolve_carrier_id(delivery_method)
        try:
            return self._create_shipment_payload(
                order_id,
                checkout_form_id,
                order_data,
                delivery_method_id,
                carrier_id,
            )
        except Exception as exc:
            self._log_creation_error(order_id, exc)
            return []

    def _resolve_delivery_method(
        self,
        order_id: str,
        checkout_form_id: str,
        delivery_method: str,
    ) -> tuple[Optional[str], str]:
        delivery_method_id = None
        try:
            allegro_detail = self.fetch_order_detail(checkout_form_id)
            allegro_delivery = (allegro_detail.get("delivery") or {}).get("method") or {}
            delivery_method_id = allegro_delivery.get("id")
            if not delivery_method:
                delivery_method = allegro_delivery.get("name", "")
            self.logger.info(
                "Pobrano delivery_method_id=%s z checkout-form (Allegro Standard/SMART) "
                "dla zamowienia %s (metoda: %s)",
                delivery_method_id,
                order_id,
                delivery_method,
            )
        except Exception as exc:
            self.logger.warning(
                "Nie mozna pobrac delivery.method.id z Allegro API dla %s: %s",
                checkout_form_id,
                exc,
            )

        if delivery_method_id:
            return delivery_method_id, delivery_method

        self.logger.warning(
            "Uzyto fallback _resolve_delivery_service_id dla zamowienia %s "
            "(delivery_method='%s') - checkout form nie zwrocil delivery.method.id",
            order_id,
            delivery_method,
        )
        return self.resolve_delivery_service_id(delivery_method), delivery_method

    def _create_shipment_payload(
        self,
        order_id: str,
        checkout_form_id: str,
        order_data: Dict[str, Any],
        delivery_method_id: str,
        carrier_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        packages, reference_number = build_packages(order_data.get("products", []))
        command_result = self.create_shipment(
            delivery_method_id=delivery_method_id,
            sender=build_sender(self.settings_store),
            receiver=build_receiver(order_data),
            packages=packages,
            cash_on_delivery=build_cod_payload(order_data),
            reference_number=reference_number,
            additional_services=build_additional_services(carrier_id),
        )
        command_id = command_result.get("commandId")
        if not command_id:
            self.logger.error("Brak commandId w odpowiedzi create_shipment")
            return []

        creation_result = self.wait_for_shipment_creation(command_id)
        shipment_id = creation_result.get("shipmentId")
        if not shipment_id:
            self.logger.error("Brak shipmentId po utworzeniu (commandId=%s)", command_id)
            return []

        waybill = self._load_waybill(shipment_id)
        self._sync_tracking_and_fulfillment(
            checkout_form_id,
            order_id,
            carrier_id,
            waybill,
        )
        self.save_state_value(f"sm_shipment:{order_id}", shipment_id)

        self.logger.info(
            "Utworzono przesylke %s (waybill: %s) dla zamowienia %s",
            shipment_id,
            waybill,
            order_id,
        )
        return [
            {
                "shipment_id": shipment_id,
                "waybill": waybill,
                "carrier_id": carrier_id or "",
                "courier_code": carrier_id or "",
                "courier_package_nr": waybill,
            }
        ]

    def _load_waybill(self, shipment_id: str) -> str:
        try:
            details = self.get_shipment_details(shipment_id)
            for package in details.get("packages", []):
                waybill = package.get("waybill", "")
                if waybill:
                    return waybill
        except Exception as exc:
            self.logger.warning(
                "Nie mozna pobrac szczegolow przesylki %s: %s",
                shipment_id,
                exc,
            )
        return ""

    def _sync_tracking_and_fulfillment(
        self,
        checkout_form_id: str,
        order_id: str,
        carrier_id: Optional[str],
        waybill: str,
    ) -> None:
        if waybill and carrier_id:
            try:
                self.add_shipment_tracking(
                    checkout_form_id,
                    carrier_id=carrier_id,
                    waybill=waybill,
                )
            except Exception as exc:
                self.logger.warning(
                    "Nie mozna dodac trackingu %s do zamowienia %s: %s",
                    waybill,
                    order_id,
                    exc,
                )

        try:
            self.update_fulfillment_status(checkout_form_id, "PROCESSING")
        except Exception as exc:
            self.logger.warning(
                "Nie mozna zmienic statusu fulfillment dla %s: %s",
                order_id,
                exc,
            )

    def _log_creation_error(self, order_id: str, exc: Exception) -> None:
        self.logger.error("Blad tworzenia przesylki dla zamowienia %s: %s", order_id, exc)
        response = getattr(exc, "response", None)
        if response is None:
            return

        try:
            error_body = response.json()
            errors = error_body.get("errors", [])
            for error in errors:
                self.logger.error(
                    "  SM API error: path=%s code=%s message=%s userMessage=%s",
                    error.get("path"),
                    error.get("code"),
                    error.get("message"),
                    error.get("userMessage"),
                )
            if not errors:
                self.logger.error("  SM API response body: %s", response.text[:500])
        except Exception:
            self.logger.error("  SM API response body: %s", response.text[:500])


__all__ = ["PrintShipmentCreator"]