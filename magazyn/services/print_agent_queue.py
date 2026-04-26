"""Przetwarzanie kolejki etykiet agenta drukowania."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Type


class PrintQueueProcessor:
    """Drukuje zalegle etykiety zapisane w kolejce."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        is_quiet_time: Callable[[], bool],
        save_queue: Callable[[List[Dict[str, Any]]], None],
        mark_as_printed: Callable[[str, Any], None],
        notify_messenger: Callable[[Dict[str, Any], bool], None],
        retry: Callable[..., Any],
        print_label: Callable[[str, str, str], None],
        consume_order_stock: Callable[[List[Dict[str, Any]]], None],
        print_error_type: Type[Exception],
        errors_total: Any,
        now: Callable[[], datetime],
        max_queue_retries: int = 10,
    ):
        self.logger = logger
        self.is_quiet_time = is_quiet_time
        self.save_queue = save_queue
        self.mark_as_printed = mark_as_printed
        self.notify_messenger = notify_messenger
        self.retry = retry
        self.print_label = print_label
        self.consume_order_stock = consume_order_stock
        self.print_error_type = print_error_type
        self.errors_total = errors_total
        self.now = now
        self.max_queue_retries = max_queue_retries

    def process(
        self,
        queue: List[Dict[str, Any]],
        printed: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if self.is_quiet_time():
            return queue

        grouped = self._group_by_order(queue)
        new_queue: List[Dict[str, Any]] = []
        for order_id, items in grouped.items():
            if self._is_retry_limit_reached(order_id, items):
                continue

            retry_count = items[0].get("retry_count", 0)
            try:
                self._print_items(queue, items)
                last_order_data = items[0].get("last_order_data", {})
                self.consume_order_stock(last_order_data.get("products", []))
                self.mark_as_printed(order_id, last_order_data)
                printed[order_id] = self.now()
                self.notify_messenger(last_order_data, True)
            except Exception as exc:
                self.logger.error(
                    "Blad przetwarzania z kolejki (proba %d/%d): %s",
                    retry_count + 1,
                    self.max_queue_retries,
                    exc,
                )
                self._restore_items_for_retry(items, retry_count + 1)
                new_queue.extend(items)
                self.errors_total.labels(stage="queue").inc()

        return new_queue

    def _group_by_order(
        self,
        queue: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in queue:
            grouped.setdefault(item["order_id"], []).append(item)
        return grouped

    def _is_retry_limit_reached(
        self,
        order_id: str,
        items: List[Dict[str, Any]],
    ) -> bool:
        retry_count = items[0].get("retry_count", 0)
        if retry_count < self.max_queue_retries:
            return False

        self.logger.error(
            "Zamowienie %s przekroczylo limit %d prob drukowania - usuwam z kolejki",
            order_id,
            self.max_queue_retries,
        )
        last_order_data = items[0].get("last_order_data")
        self.mark_as_printed(order_id, last_order_data)
        self.notify_messenger(items[0].get("last_order_data", {}), False)
        return True

    def _print_items(
        self,
        queue: List[Dict[str, Any]],
        items: List[Dict[str, Any]],
    ) -> None:
        for item in items:
            item["status"] = "in_progress"
        self.save_queue(queue)

        for item in items:
            self.retry(
                self.print_label,
                item["label_data"],
                item.get("ext", "pdf"),
                item["order_id"],
                stage="print",
                retry_exceptions=(self.print_error_type,),
            )

    def _restore_items_for_retry(
        self,
        items: List[Dict[str, Any]],
        retry_count: int,
    ) -> None:
        for item in items:
            item["status"] = "queued"
            item["retry_count"] = retry_count


__all__ = ["PrintQueueProcessor"]