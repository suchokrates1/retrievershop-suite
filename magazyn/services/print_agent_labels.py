"""Pobieranie etykiet i obsluga wygaslych przesylek agenta drukowania."""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from .print_agent_errors import ApiError, ShipmentExpiredError


@dataclass
class CollectedLabels:
    labels: List[Tuple[str, str]]
    courier_code: str
    package_ids: List[str]
    tracking_numbers: List[str]


class PrintLabelService:
    """Operacje na etykietach Allegro Shipment Management."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        get_shipment_label: Callable[..., bytes],
        cancel_shipment: Callable[[str], None],
        create_shipment: Callable[[str, str], List[Dict[str, Any]]],
        fetch_label: Callable[[str, str], Tuple[str, str]],
        recreate_shipment_and_get_label: Callable[
            [str, str, str, List[str], List[str]],
            Tuple[str, str],
        ],
        retry: Callable[..., Any],
        errors_total: Any,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.logger = logger
        self.get_shipment_label = get_shipment_label
        self.cancel_shipment = cancel_shipment
        self.create_shipment = create_shipment
        self.fetch_label = fetch_label
        self.recreate_shipment_and_get_label_callback = recreate_shipment_and_get_label
        self.retry = retry
        self.errors_total = errors_total
        self.sleep = sleep

    def get_label(self, courier_code: str, package_id: str) -> Tuple[str, str]:
        """Pobierz etykiete przesylki z Allegro Shipment Management API."""
        if not package_id:
            raise ApiError("Brak ID przesylki do pobrania etykiety")

        try:
            return self._fetch_label_attempt(courier_code, package_id, 1)
        except RuntimeError as exc:
            self.logger.warning("Etykieta nie gotowa dla %s: %s", package_id, exc)
            self.sleep(3)
            try:
                return self._fetch_label_attempt(courier_code, package_id, 2)
            except Exception as retry_exc:
                raise ApiError(f"Etykieta niedostepna: {retry_exc}") from retry_exc
        except Exception as exc:
            status_code = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )
            if status_code == 403:
                raise ShipmentExpiredError(package_id, str(exc)) from exc
            raise ApiError(f"Blad pobierania etykiety: {exc}") from exc

    def recreate_shipment_and_get_label(
        self,
        order_id: str,
        old_shipment_id: str,
        courier_code: str,
        package_ids: List[str],
        tracking_numbers: List[str],
    ) -> Tuple[str, str]:
        """Anuluj wygasla przesylke, utworz nowa i pobierz etykiete."""
        checkout_form_id = order_id
        if order_id.startswith("allegro_"):
            checkout_form_id = order_id[len("allegro_"):]

        try:
            self.cancel_shipment(old_shipment_id)
            self.logger.info("Anulowano wygasla przesylke %s", old_shipment_id)
        except Exception as exc:
            self.logger.warning(
                "Nie mozna anulowac przesylki %s (moze juz anulowana): %s",
                old_shipment_id,
                exc,
            )

        if old_shipment_id in package_ids:
            package_ids.remove(old_shipment_id)

        try:
            new_packages = self.create_shipment(order_id, checkout_form_id)
        except Exception as exc:
            self.logger.error(
                "Blad tworzenia nowej przesylki dla %s: %s",
                order_id,
                exc,
            )
            return "", ""

        if not new_packages:
            self.logger.error("Nie utworzono nowej przesylki dla %s", order_id)
            return "", ""

        new_shipment_id = None
        for package in new_packages:
            shipment_id = package.get("shipment_id")
            waybill = package.get("waybill") or package.get("courier_package_nr")
            if shipment_id:
                new_shipment_id = str(shipment_id)
                package_ids.append(new_shipment_id)
            if waybill:
                tracking_numbers.append(str(waybill))

        if not new_shipment_id:
            self.logger.error("Brak shipment_id w nowej przesylce dla %s", order_id)
            return "", ""

        self.logger.info(
            "Utworzono nowa przesylke %s (stara: %s) dla zamowienia %s",
            new_shipment_id,
            old_shipment_id,
            order_id,
        )

        try:
            return self.fetch_label(courier_code, new_shipment_id)
        except Exception as exc:
            self.logger.error(
                "Blad pobierania etykiety z nowej przesylki %s: %s",
                new_shipment_id,
                exc,
            )
            return "", ""

    def collect_order_labels(
        self,
        order_id: str,
        packages: List[Dict[str, Any]],
    ) -> CollectedLabels:
        labels: List[Tuple[str, str]] = []
        courier_code = ""
        package_ids: List[str] = []
        tracking_numbers: List[str] = []

        for package in packages:
            shipment_id = package.get("shipment_id")
            code = package.get("carrier_id") or package.get("courier_code")
            tracking_number = package.get("waybill") or package.get("courier_package_nr")
            if code and not courier_code:
                courier_code = code
            if shipment_id:
                package_ids.append(str(shipment_id))
            if tracking_number:
                tracking_numbers.append(str(tracking_number))
            if not shipment_id:
                self.logger.warning("  Brak shipment_id dla zamowienia %s", order_id)
                continue

            label_data, extension = self._fetch_package_label(
                order_id,
                str(shipment_id),
                courier_code,
                package_ids,
                tracking_numbers,
            )
            if label_data:
                labels.append((label_data, extension))

        return CollectedLabels(labels, courier_code, package_ids, tracking_numbers)

    def _fetch_label_attempt(
        self,
        courier_code: str,
        package_id: str,
        logical_attempt: int,
    ) -> Tuple[str, str]:
        self.logger.info(
            "Proba pobrania etykiety: shipment_id=%s courier_code=%s attempt=%d",
            package_id,
            courier_code or "",
            logical_attempt,
        )
        label_bytes = self.get_shipment_label(
            [package_id],
            page_size="A6",
            cut_line=False,
        )
        label_base64 = base64.b64encode(label_bytes).decode("ascii")
        self.logger.info(
            "Pobrano etykiete: shipment_id=%s courier_code=%s attempt=%d bytes=%d",
            package_id,
            courier_code or "",
            logical_attempt,
            len(label_bytes),
        )
        return label_base64, "pdf"

    def _fetch_package_label(
        self,
        order_id: str,
        shipment_id: str,
        courier_code: str,
        package_ids: List[str],
        tracking_numbers: List[str],
    ) -> Tuple[str, str]:
        try:
            return self.retry(
                self.fetch_label,
                courier_code,
                shipment_id,
                stage="label",
                retry_exceptions=(ApiError,),
            )
        except ShipmentExpiredError:
            self.logger.warning(
                "Przesylka %s wygasla (403) - anuluje i tworze nowa dla %s",
                shipment_id,
                order_id,
            )
            label_data, extension = self.recreate_shipment_and_get_label_callback(
                order_id,
                shipment_id,
                courier_code,
                package_ids,
                tracking_numbers,
            )
            if not label_data:
                self.errors_total.labels(stage="loop").inc()
            return label_data, extension
        except ApiError as exc:
            self.logger.error(
                "Blad pobierania etykiety %s/%s: %s",
                courier_code,
                shipment_id,
                exc,
            )
            self.errors_total.labels(stage="loop").inc()
            return "", ""


__all__ = ["CollectedLabels", "PrintLabelService"]