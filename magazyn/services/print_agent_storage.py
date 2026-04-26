"""Persistence agenta drukowania: kolejka, historia i stan."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ..db import db_connect, table_has_column
from ..metrics import PRINT_QUEUE_OLDEST_AGE_SECONDS, PRINT_QUEUE_SIZE
from ..parsing import parse_product_info


@dataclass
class SuccessMarker:
    order_id: Optional[str]
    timestamp: Optional[str]


class PrintAgentStorage:
    """Operacje zapisu i odczytu agenta drukowania."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        now: Callable[[], datetime],
        handle_readonly_error: Callable[[str, Exception], bool],
    ):
        self.logger = logger
        self._now = now
        self._handle_readonly_error = handle_readonly_error

    def ensure_db(self) -> None:
        try:
            with db_connect() as conn:
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS printed_orders("
                    "order_id TEXT PRIMARY KEY, printed_at TEXT, last_order_data TEXT)"
                ))
                if not table_has_column("printed_orders", "last_order_data"):
                    conn.execute(text(
                        "ALTER TABLE printed_orders ADD COLUMN last_order_data TEXT"
                    ))
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS label_queue("
                    "order_id TEXT, label_data TEXT, ext TEXT, last_order_data TEXT,"
                    " queued_at TEXT, status TEXT, retry_count INTEGER DEFAULT 0)"
                ))
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS agent_state("
                    "key TEXT PRIMARY KEY, value TEXT)"
                ))
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS allegro_replied_threads("
                    "thread_id TEXT PRIMARY KEY, replied_at TEXT)"
                ))
                for col, default in [
                    ("queued_at", None),
                    ("status", "'queued'"),
                    ("retry_count", "0"),
                ]:
                    if not table_has_column("label_queue", col):
                        ddl = f"ALTER TABLE label_queue ADD COLUMN {col}"
                        ddl += f" TEXT DEFAULT {default}" if default and col != "retry_count" else ""
                        if col == "retry_count":
                            ddl += " INTEGER DEFAULT 0"
                        try:
                            conn.execute(text(ddl))
                        except (DBAPIError, Exception):
                            pass

                rows = conn.execute(text(
                    "SELECT order_id, last_order_data FROM printed_orders"
                )).fetchall()
                for order_id, data_json in rows:
                    try:
                        data = json.loads(data_json) if data_json else {}
                    except Exception as exc:
                        self.logger.debug(
                            "Pominieto uszkodzone last_order_data dla %s: %s",
                            order_id,
                            exc,
                        )
                        continue
                    name = (data.get("name") or "").strip()
                    customer = (data.get("customer") or "").strip()
                    if name and customer and name == customer:
                        product_name, size, color = parse_product_info(
                            (data.get("products") or [{}])[0]
                        )
                        data["name"] = product_name
                        data["size"] = size
                        data["color"] = color
                        conn.execute(
                            text("UPDATE printed_orders SET last_order_data = :data WHERE order_id = :oid"),
                            {"data": json.dumps(data), "oid": order_id},
                        )
        except (DBAPIError, Exception) as exc:
            if self._handle_readonly_error("database migrations", exc):
                return
            err_msg = str(exc).lower()
            if "unique" in err_msg and ("pg_type" in err_msg or "already exists" in err_msg):
                self.logger.debug("ensure_db: tabele juz istnieja (race condition) - pomijam")
                return
            self.logger.error("Blad ensure_db: %s", exc)
            raise

    def load_printed_orders(self) -> List[Dict[str, Any]]:
        self.ensure_db()
        with db_connect() as conn:
            rows = conn.execute(text(
                "SELECT order_id, printed_at, last_order_data FROM printed_orders ORDER BY printed_at DESC"
            )).fetchall()
        items: List[Dict[str, Any]] = []
        for order_id, timestamp, data_json in rows:
            try:
                data = json.loads(data_json) if data_json else {}
            except Exception:  # pragma: no cover - defensive
                data = {}
            items.append(
                {
                    "order_id": order_id,
                    "printed_at": datetime.fromisoformat(timestamp),
                    "last_order_data": data,
                }
            )
        return items

    def mark_as_printed(
        self,
        order_id: str,
        last_order_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        data_json = json.dumps(last_order_data or {})
        try:
            with db_connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO printed_orders(order_id, printed_at, last_order_data) "
                        "VALUES (:oid, :ts, :data) "
                        "ON CONFLICT(order_id) DO UPDATE SET last_order_data = excluded.last_order_data"
                    ),
                    {"oid": order_id, "ts": self._now().isoformat(), "data": data_json},
                )
        except (DBAPIError, Exception) as exc:
            if self._handle_readonly_error("mark_as_printed", exc):
                return
            raise

        try:
            from ..db import get_session
            from .order_status import add_order_status

            with get_session() as db:
                add_order_status(
                    db,
                    order_id,
                    "wydrukowano",
                    courier_code=last_order_data.get("courier_code") if last_order_data else None,
                    tracking_number=last_order_data.get("delivery_package_nr") if last_order_data else None,
                )
                db.commit()
        except Exception as status_exc:
            self.logger.warning(
                "Could not update order status for %s: %s", order_id, status_exc
            )

    def load_state_value(self, key: str) -> Optional[str]:
        self.ensure_db()
        with db_connect() as conn:
            row = conn.execute(
                text("SELECT value FROM agent_state WHERE key = :k"), {"k": key}
            ).fetchone()
        return row[0] if row else None

    def save_state_value(self, key: str, value: Optional[str]) -> None:
        self.ensure_db()
        try:
            with db_connect() as conn:
                if value is None:
                    conn.execute(text("DELETE FROM agent_state WHERE key = :k"), {"k": key})
                else:
                    conn.execute(
                        text(
                            "INSERT INTO agent_state(key, value) VALUES (:k, :v) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                        ),
                        {"k": key, "v": value},
                    )
        except (DBAPIError, Exception) as exc:
            if self._handle_readonly_error("save agent state", exc):
                return
            raise

    def load_last_success_marker(self) -> SuccessMarker:
        return SuccessMarker(
            order_id=self.load_state_value("last_success_order_id"),
            timestamp=self.load_state_value("last_success_timestamp"),
        )

    def update_last_success_marker(
        self,
        order_id: Optional[str],
        timestamp: Optional[str] = None,
    ) -> None:
        if timestamp is None:
            timestamp = self._now().isoformat()
        self.save_state_value("last_success_timestamp", timestamp)
        if order_id is not None:
            self.save_state_value("last_success_order_id", order_id)

    def clean_old_printed_orders(self, printed_expiry_days: int) -> None:
        threshold = self._now() - timedelta(days=printed_expiry_days)
        try:
            with db_connect() as conn:
                conn.execute(
                    text("DELETE FROM printed_orders WHERE printed_at < :ts"),
                    {"ts": threshold.isoformat()},
                )
        except (DBAPIError, Exception) as exc:
            if self._handle_readonly_error("clean_old_printed_orders", exc):
                return
            raise

    def deduplicate_queue(self, queue: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items = list(queue)
        seen: set[tuple] = set()
        unique: List[Dict[str, Any]] = []
        for item in items:
            key = (
                item.get("order_id"),
                item.get("ext"),
                item.get("label_data"),
            )
            if key in seen:
                self.logger.debug("Dropping duplicate queue entry for %s", item.get("order_id"))
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def update_queue_metrics(self, queue: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        queue_list = self.deduplicate_queue(queue)
        PRINT_QUEUE_SIZE.set(len(queue_list))

        oldest = None
        for item in queue_list:
            queued_at = item.get("queued_at")
            if not queued_at:
                continue
            try:
                queued_time = datetime.fromisoformat(queued_at)
            except ValueError:  # pragma: no cover - defensive
                continue
            if oldest is None or queued_time < oldest:
                oldest = queued_time

        if oldest is not None:
            age = max(0.0, (self._now() - oldest).total_seconds())
            PRINT_QUEUE_OLDEST_AGE_SECONDS.set(age)
        else:
            PRINT_QUEUE_OLDEST_AGE_SECONDS.set(0)

        return queue_list

    def load_queue(self) -> List[Dict[str, Any]]:
        self.ensure_db()
        with db_connect() as conn:
            rows = conn.execute(text(
                "SELECT order_id, label_data, ext, last_order_data, queued_at, status, retry_count FROM label_queue"
            )).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            order_id, label_data, ext, last_order_json, queued_at, status = row[:6]
            retry_count = row[6] if len(row) > 6 else 0
            try:
                last_data = json.loads(last_order_json) if last_order_json else {}
            except Exception:  # pragma: no cover - defensive
                last_data = {}
            if not queued_at:
                queued_at = self._now().isoformat()
            items.append(
                {
                    "order_id": order_id,
                    "label_data": label_data,
                    "ext": ext,
                    "last_order_data": last_data,
                    "queued_at": queued_at,
                    "status": status or "queued",
                    "retry_count": retry_count or 0,
                }
            )
        deduped = self.deduplicate_queue(items)
        if len(deduped) != len(items):
            self.logger.info(
                "Removed %s duplicate queue entries from storage",
                len(items) - len(deduped),
            )
            self.save_queue(deduped)
        return deduped

    def save_queue(self, items: Iterable[Dict[str, Any]]) -> None:
        items_list = self.update_queue_metrics(items)

        try:
            with db_connect() as conn:
                conn.execute(text("DELETE FROM label_queue"))
                for item in items_list:
                    conn.execute(
                        text(
                            "INSERT INTO label_queue(order_id, label_data, ext, last_order_data, queued_at, status, retry_count)"
                            " VALUES (:oid, :ldata, :ext, :odata, :qat, :st, :rc)"
                        ),
                        {
                            "oid": item.get("order_id"),
                            "ldata": item.get("label_data"),
                            "ext": item.get("ext"),
                            "odata": json.dumps(item.get("last_order_data", {}), default=str),
                            "qat": item.get("queued_at"),
                            "st": item.get("status", "queued"),
                            "rc": item.get("retry_count", 0),
                        },
                    )
        except (DBAPIError, Exception) as exc:
            if self._handle_readonly_error("save_queue", exc):
                return
            raise


__all__ = ["PrintAgentStorage", "SuccessMarker"]