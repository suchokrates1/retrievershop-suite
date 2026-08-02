"""Przetwarzanie pojedynczego zamowienia przez agenta drukowania."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple, Type

from .print_agent_config import is_cod_order
from .print_agent_errors import ApiError, IncompleteReceiverData
from .print_agent_order_data import apply_package_tracking, build_last_order_data
from .print_agent_status import set_print_error_status

# Race Allegro BOUGHT/FILLED_IN vs READY_FOR_PROCESSING — nie alertuj od razu.
INCOMPLETE_RECEIVER_SOFT_SKIP_SECONDS = 20 * 60


def should_soft_skip_incomplete_receiver(
    order: Dict[str, Any],
    *,
    now: datetime,
    soft_skip_seconds: int = INCOMPLETE_RECEIVER_SOFT_SKIP_SECONDS,
) -> bool:
    """True gdy zamowienie jest mlode i brak danych odbiorcy to jeszcze race, nie awaria."""
    date_add = order.get("date_add")
    if date_add is None:
        return False
    try:
        age_seconds = now.timestamp() - float(date_add)
    except (TypeError, ValueError):
        return False
    return age_seconds < soft_skip_seconds


class PrintOrderProcessor:
    """Obsluguje jeden order w iteracji agenta drukowania."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        set_last_order_data: Callable[[Dict[str, Any]], None],
        retry: Callable[..., Any],
        get_order_packages: Callable[[str], List[Dict[str, Any]]],
        collect_order_labels: Callable[[str, List[Dict[str, Any]]], Any],
        is_quiet_time: Callable[[], bool],
        save_queue: Callable[[List[Dict[str, Any]]], None],
        print_label: Callable[[str, str, str], None],
        mark_as_printed: Callable[[str, Dict[str, Any]], None],
        notify_messenger: Callable[[Dict[str, Any], bool], None],
        consume_order_stock: Callable[..., None],
        should_send_error_notification: Callable[[str], bool],
        send_label_error_notification: Callable[[str], None],
        increment_error_notification: Callable[[str], None],
        wait: Callable[[float], Any],
        errors_total: Any,
        print_error_type: Type[Exception],
        now: Callable[[], datetime],
    ):
        self.logger = logger
        self.set_last_order_data = set_last_order_data
        self.retry = retry
        self.get_order_packages = get_order_packages
        self.collect_order_labels = collect_order_labels
        self.is_quiet_time = is_quiet_time
        self.save_queue = save_queue
        self.print_label = print_label
        self.mark_as_printed = mark_as_printed
        self.notify_messenger = notify_messenger
        self.consume_order_stock = consume_order_stock
        self.should_send_error_notification = should_send_error_notification
        self.send_label_error_notification = send_label_error_notification
        self.increment_error_notification = increment_error_notification
        self.wait = wait
        self.errors_total = errors_total
        self.print_error_type = print_error_type
        self.now = now

    def process(
        self,
        order: Dict[str, Any],
        queue: List[Dict[str, Any]],
        printed: Dict[str, Any],
    ) -> None:
        order_id = str(order["order_id"])
        last_order_data = build_last_order_data(order)
        self.set_last_order_data(last_order_data)

        if self._should_skip_order(order, order_id, queue, printed):
            return

        try:
            packages = self._load_packages(order_id)
        except IncompleteReceiverData as exc:
            self._handle_incomplete_receiver(order_id, order, exc)
            return
        if packages is None:
            return

        collected_labels = self.collect_order_labels(
            order_id,
            packages,
            delivery_method=str(order.get("delivery_method") or order.get("shipping") or ""),
        )
        apply_package_tracking(
            last_order_data,
            courier_code=collected_labels.courier_code,
            package_ids=collected_labels.package_ids,
            tracking_numbers=collected_labels.tracking_numbers,
        )

        if collected_labels.labels:
            self._handle_labels(order_id, last_order_data, collected_labels.labels, queue, printed)
        else:
            self._handle_missing_labels(order_id)

    def _should_skip_order(
        self,
        order: Dict[str, Any],
        order_id: str,
        queue: List[Dict[str, Any]],
        printed: Dict[str, Any],
    ) -> bool:
        if order_id in printed:
            return True

        queued_order_ids = {item["order_id"] for item in queue}
        if order_id in queued_order_ids:
            return True

        payment_done = float(order.get("payment_done") or 0)
        is_cod = is_cod_order(
            order.get("payment_method_cod", "0"),
            order.get("payment_method", ""),
        )
        if not is_cod and payment_done <= 0:
            self.logger.info(
                "Pomijam %s - nieoplacone (payment_done=%.2f, cod=%s)",
                order_id,
                payment_done,
                is_cod,
            )
            return True

        return False

    def _load_packages(self, order_id: str) -> List[Dict[str, Any]] | None:
        try:
            return self.retry(
                self.get_order_packages,
                order_id,
                stage="packages",
                retry_exceptions=(ApiError,),
            )
        except IncompleteReceiverData:
            raise
        except ApiError as exc:
            self.logger.error("Blad pobierania paczek dla %s: %s", order_id, exc)
            self.errors_total.labels(stage="loop").inc()
            self._notify_label_error(order_id)
            return None

    def _handle_labels(
        self,
        order_id: str,
        last_order_data: Dict[str, Any],
        labels: List[Tuple[str, str]],
        queue: List[Dict[str, Any]],
        printed: Dict[str, Any],
    ) -> None:
        if self.is_quiet_time():
            self._queue_quiet_time_labels(order_id, last_order_data, labels, queue, printed)
            return

        self._print_labels_now(order_id, last_order_data, labels, queue, printed)

    def _queue_quiet_time_labels(
        self,
        order_id: str,
        last_order_data: Dict[str, Any],
        labels: List[Tuple[str, str]],
        queue: List[Dict[str, Any]],
        printed: Dict[str, Any],
    ) -> None:
        for label_data, extension in labels:
            queue.append(
                self._queue_entry(order_id, label_data, extension, last_order_data, "queued")
            )
        self.notify_messenger(last_order_data, True)
        self.mark_as_printed(order_id, last_order_data)
        printed[order_id] = self.now()

    def _print_labels_now(
        self,
        order_id: str,
        last_order_data: Dict[str, Any],
        labels: List[Tuple[str, str]],
        queue: List[Dict[str, Any]],
        printed: Dict[str, Any],
    ) -> None:
        entries = [
            self._queue_entry(order_id, label_data, extension, last_order_data, "in_progress")
            for label_data, extension in labels
        ]
        queue.extend(entries)
        self.save_queue(queue)

        print_success = True
        try:
            for entry in entries:
                self.retry(
                    self.print_label,
                    entry["label_data"],
                    entry.get("ext", "pdf"),
                    entry["order_id"],
                    stage="print",
                    retry_exceptions=(self.print_error_type,),
                )
            self.consume_order_stock(last_order_data.get("products", []), order_id=order_id)
            self.mark_as_printed(order_id, last_order_data)
            printed[order_id] = self.now()
            for entry in entries:
                if entry in queue:
                    queue.remove(entry)
        except Exception as exc:
            self.logger.error("Blad drukowania zamowienia %s: %s", order_id, exc)
            print_success = False
            set_print_error_status(order_id, f"Blad drukowania: {exc}", self.logger)
            for entry in entries:
                entry["status"] = "queued"
            self.save_queue(queue)
            self.logger.info("Retry za 60s dla %s", order_id)
            self.wait(60)

        self.notify_messenger(last_order_data, print_success)

    def _handle_incomplete_receiver(
        self,
        order_id: str,
        order: Dict[str, Any],
        exc: IncompleteReceiverData,
    ) -> None:
        if should_soft_skip_incomplete_receiver(order, now=self.now()):
            self.logger.info(
                "Czekam na dane odbiorcy dla %s (%s) - soft-skip bez blad_druku",
                order_id,
                exc.reason,
            )
            self.logger.info("Retry za 60s dla %s", order_id)
            self.wait(60)
            return

        self.logger.error(
            "Brak danych odbiorcy dla %s po timeoutcie soft-skip: %s",
            order_id,
            exc.reason,
        )
        self.errors_total.labels(stage="label").inc()
        set_print_error_status(
            order_id,
            f"Brak danych odbiorcy (telefon/imie) po 20 min: {exc.reason}",
            self.logger,
        )
        self._notify_label_error(order_id)
        self.logger.info("Retry za 60s dla %s", order_id)
        self.wait(60)

    def _handle_missing_labels(self, order_id: str) -> None:
        self.logger.error(
            "Brak etykiety dla zamowienia %s (Allegro nie zwrocilo danych)",
            order_id,
        )
        self.errors_total.labels(stage="label").inc()
        set_print_error_status(
            order_id,
            "Brak etykiety - Allegro nie zwrocilo danych",
            self.logger,
        )
        self._notify_label_error(order_id)
        self.logger.info("Retry za 60s dla %s", order_id)
        self.wait(60)

    def _notify_label_error(self, order_id: str) -> None:
        if self.should_send_error_notification(order_id):
            self.send_label_error_notification(order_id)
        else:
            self.increment_error_notification(order_id)

    def _queue_entry(
        self,
        order_id: str,
        label_data: str,
        extension: str,
        last_order_data: Dict[str, Any],
        status: str,
    ) -> Dict[str, Any]:
        return {
            "order_id": order_id,
            "label_data": label_data,
            "ext": extension,
            "last_order_data": last_order_data,
            "queued_at": self.now().isoformat(),
            "status": status,
        }


__all__ = [
    "INCOMPLETE_RECEIVER_SOFT_SKIP_SECONDS",
    "PrintOrderProcessor",
    "should_soft_skip_incomplete_receiver",
]