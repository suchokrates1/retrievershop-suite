from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import threading
import time

# fcntl is Unix-only, provide fallback for Windows
try:
    import fcntl
except ImportError:
    fcntl = None
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, time as dt_time, timezone
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple, Type, TypeVar
from zoneinfo import ZoneInfo

import requests
import sqlite3
from requests.exceptions import HTTPError

from .config import load_config, settings
from .db import sqlite_connect
from .notifications import send_report, send_messenger
from .parsing import parse_product_info
from .services import consume_order_stock, get_sales_summary
from .utils import short_preview
from .allegro_token_refresher import token_refresher
from .allegro_api import (
    fetch_discussions,
    fetch_discussion_chat,
    fetch_message_threads,
    fetch_thread_messages,
    send_discussion_message,
    send_thread_message,
)
from .allegro_api.shipment_management import (
    create_shipment,
    get_delivery_services,
    get_shipment_details,
    get_shipment_label,
)
from .allegro_api.fulfillment import (
    add_shipment_tracking,
    update_fulfillment_status,
)
from .agent.allegro_sync import AllegroSyncService
from .metrics import (
    PRINT_AGENT_DOWNTIME_SECONDS,
    PRINT_AGENT_ITERATION_SECONDS,
    PRINT_AGENT_RETRIES_TOTAL,
    PRINT_LABEL_ERRORS_TOTAL,
    PRINT_LABELS_TOTAL,
    PRINT_QUEUE_OLDEST_AGE_SECONDS,
    PRINT_QUEUE_SIZE,
)


class ConfigError(Exception):
    """Raised when required configuration is missing."""


class ApiError(Exception):
    """Raised when an API call fails."""


class PrintError(Exception):
    """Raised when sending data to the printer fails."""


T = TypeVar("T")


def parse_time_str(value: str) -> dt_time:
    """Return time from ``HH:MM`` or raise ``ValueError``."""
    try:
        return dt_time.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid time value: {value}") from exc


# Uzywamy short_preview z modulu utils


@dataclass
class AgentConfig:
    api_token: str
    page_access_token: str
    recipient_id: str
    status_id: str
    printer_name: str
    cups_server: Optional[str]
    cups_port: Optional[int]
    poll_interval: int
    quiet_hours_start: dt_time
    quiet_hours_end: dt_time
    timezone: str
    printed_expiry_days: int
    enable_weekly_reports: bool
    enable_monthly_reports: bool
    log_level: str
    log_file: str
    db_file: str
    lock_file: str
    base_url: str = ""  # nieuzywane - zachowane dla kompatybilnosci konfiguracji
    legacy_printed_file: Optional[str] = None
    legacy_queue_file: Optional[str] = None
    legacy_db_file: Optional[str] = None
    api_rate_limit_calls: int = 60
    api_rate_limit_period: float = 60.0
    api_retry_attempts: int = 3
    api_retry_backoff_initial: float = 1.0
    api_retry_backoff_max: float = 30.0

    @classmethod
    def from_settings(cls, cfg: Any) -> "AgentConfig":
        base_dir = os.path.dirname(__file__)
        log_file = cfg.LOG_FILE
        lock_file = os.getenv(
            "AGENT_LOCK_FILE",
            os.path.join(os.path.dirname(log_file), "agent.lock"),
        )
        return cls(
            api_token=cfg.API_TOKEN,
            page_access_token=cfg.PAGE_ACCESS_TOKEN,
            recipient_id=cfg.RECIPIENT_ID,
            status_id=cfg.STATUS_ID,
            printer_name=cfg.PRINTER_NAME,
            cups_server=cfg.CUPS_SERVER,
            cups_port=int(cfg.CUPS_PORT) if cfg.CUPS_PORT else None,
            poll_interval=int(cfg.POLL_INTERVAL),
            quiet_hours_start=parse_time_str(cfg.QUIET_HOURS_START),
            quiet_hours_end=parse_time_str(cfg.QUIET_HOURS_END),
            timezone=cfg.TIMEZONE,
            printed_expiry_days=cfg.PRINTED_EXPIRY_DAYS,
            enable_weekly_reports=cfg.ENABLE_WEEKLY_REPORTS,
            enable_monthly_reports=cfg.ENABLE_MONTHLY_REPORTS,
            log_level=cfg.LOG_LEVEL,
            log_file=log_file,
            db_file=getattr(cfg, "DB_PATH", settings.DB_PATH),
            lock_file=lock_file,
            legacy_printed_file=os.path.join(base_dir, "printed_orders.txt"),
            legacy_queue_file=os.path.join(base_dir, "queued_labels.jsonl"),
            legacy_db_file=os.path.abspath(
                os.path.join(base_dir, os.pardir, "printer", "data.db")
            ),
            api_rate_limit_calls=int(cfg.API_RATE_LIMIT_CALLS),
            api_rate_limit_period=float(cfg.API_RATE_LIMIT_PERIOD),
            api_retry_attempts=int(cfg.API_RETRY_ATTEMPTS),
            api_retry_backoff_initial=float(cfg.API_RETRY_BACKOFF_INITIAL),
            api_retry_backoff_max=float(cfg.API_RETRY_BACKOFF_MAX),
        )

    def with_updates(self, **kwargs: Any) -> "AgentConfig":
        return replace(self, **kwargs)


@dataclass
class SuccessMarker:
    order_id: Optional[str]
    timestamp: Optional[str]


class LabelAgent:
    """Encapsulates the state and behaviour of the label printing agent."""

    def __init__(self, config: AgentConfig, settings_obj: Any):
        self.config = config
        self.settings = settings_obj
        self.logger = logging.getLogger(__name__)
        self.last_order_data: Dict[str, Any] = {}
        self._agent_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._rate_limit_lock = threading.Lock()
        self._lock_handle = None
        self._api_calls_total = 0
        self._api_calls_success = 0
        self._last_api_log = datetime.now()
        self._api_call_times: Deque[float] = deque()
        self._label_error_notifications: Dict[str, int] = {}  # Śledzenie ile razy wysłano powiadomienie o błędzie
        self._configure_logging(initial=True)
        self._configure_db_engine()

    @property
    def _heartbeat_path(self) -> str:
        return f"{self.config.lock_file}.heartbeat"

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _configure_logging(self, initial: bool = False) -> None:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.config.log_level, logging.INFO))

        # Ensure we have a stream handler for console output.
        if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            root_logger.addHandler(stream_handler)

        # Replace existing file handlers so updates to LOG_FILE take effect.
        file_handlers = [h for h in root_logger.handlers if isinstance(h, logging.FileHandler)]
        for handler in file_handlers:
            root_logger.removeHandler(handler)
            handler.close()
        file_handler = logging.FileHandler(self.config.log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        self.logger.setLevel(getattr(logging, self.config.log_level, logging.INFO))
        if initial:
            self.logger.debug("LabelAgent logging configured")

    def _configure_db_engine(self) -> None:
        from . import db

        db.configure_engine(self.config.db_file)

    @staticmethod
    def _is_readonly_error(exc: sqlite3.OperationalError) -> bool:
        return "readonly" in str(exc).lower()

    def _handle_readonly_error(self, action: str, exc: sqlite3.OperationalError) -> bool:
        if self._is_readonly_error(exc):
            self.logger.warning(
                "Database %s is read-only; skipping %s: %s",
                self.config.db_file,
                action,
                exc,
            )
            return True
        return False

    def reload_config(self) -> None:
        """Reload configuration from ``.env`` and update the agent state."""
        self.settings = load_config()
        self.config = AgentConfig.from_settings(self.settings)
        self._configure_logging()
        self._configure_db_engine()
        globals()["settings"] = self.settings
        globals()["logger"] = self.logger

    # Backwards-compatible alias
    reload_env = reload_config

    # ------------------------------------------------------------------
    # Validation and persistence helpers
    # ------------------------------------------------------------------
    def _read_heartbeat(self) -> Optional[datetime]:
        try:
            with open(self._heartbeat_path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _write_heartbeat(self) -> None:
        try:
            with open(self._heartbeat_path, "w", encoding="utf-8") as handle:
                handle.write(datetime.now().isoformat())
        except OSError as exc:  # pragma: no cover - best effort logging only
            self.logger.debug("Nie można zapisać heartbeat: %s", exc)

    def _clear_heartbeat(self) -> None:
        try:
            os.remove(self._heartbeat_path)
        except OSError:
            pass

    def _cleanup_orphaned_lock(self) -> None:
        heartbeat = self._read_heartbeat()
        if heartbeat is None:
            return
        grace = max(1, self.config.poll_interval)
        max_age = timedelta(seconds=grace * 4)
        if datetime.now() - heartbeat <= max_age:
            return

        try:
            with open(self.config.lock_file, "a+", encoding="utf-8") as handle:
                try:
                    if fcntl:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # On Windows without fcntl, skip lock check
                except OSError:
                    return
        except OSError:
            self._clear_heartbeat()
            return

        try:
            os.remove(self.config.lock_file)
        except OSError:
            pass
        else:
            self.logger.warning("Wyczyszczono porzuconą blokadę agenta drukowania")
        self._clear_heartbeat()

    def _restore_in_progress(self, queue: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        restored = False
        for item in queue:
            if item.get("status") == "in_progress":
                item["status"] = "queued"
                restored = True
        if restored:
            self.save_queue(queue)
        return queue

    def _retry(
        self,
        func: Callable[..., T],
        *args: Any,
        stage: str,
        retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
        max_attempts: int = 3,
        base_delay: float = 1.0,
        **kwargs: Any,
    ) -> T:
        attempts = 0
        while True:
            try:
                return func(*args, **kwargs)
            except retry_exceptions as exc:
                attempts += 1
                if attempts >= max_attempts or self._stop_event.is_set():
                    raise
                delay = base_delay * (2 ** (attempts - 1))
                self.logger.warning(
                    "%s failed (%s). Retrying in %.1fs (attempt %s/%s)",
                    stage,
                    exc,
                    delay,
                    attempts + 1,
                    max_attempts,
                )
                PRINT_AGENT_RETRIES_TOTAL.inc()
                PRINT_AGENT_DOWNTIME_SECONDS.inc(delay)
                if self._stop_event.wait(delay):
                    raise

    def validate_env(self) -> None:
        required = {
            "API_TOKEN": self.config.api_token,
            "PAGE_ACCESS_TOKEN": self.config.page_access_token,
            "RECIPIENT_ID": self.config.recipient_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            self.logger.error(
                "Brak wymaganych zmiennych środowiskowych: %s", ", ".join(missing)
            )
            raise ConfigError("Missing environment variables: " + ", ".join(missing))

    def ensure_db(self) -> None:
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        try:
            try:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS printed_orders("  # noqa: S608 - static SQL
                    "order_id TEXT PRIMARY KEY, printed_at TEXT, last_order_data TEXT)"
                )
                cur.execute("PRAGMA table_info(printed_orders)")
                cols = [row[1] for row in cur.fetchall()]
                if "last_order_data" not in cols:
                    cur.execute(
                        "ALTER TABLE printed_orders ADD COLUMN last_order_data TEXT"
                    )
                    conn.commit()
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS label_queue("  # noqa: S608 - static SQL
                    "order_id TEXT, label_data TEXT, ext TEXT, last_order_data TEXT, queued_at TEXT, status TEXT)"
                )
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS agent_state("  # noqa: S608 - static SQL
                    "key TEXT PRIMARY KEY, value TEXT)"
                )
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS allegro_replied_threads("  # noqa: S608 - static SQL
                    "thread_id TEXT PRIMARY KEY, replied_at TEXT)"
                )
                cur.execute("PRAGMA table_info(label_queue)")
                queue_cols = [row[1] for row in cur.fetchall()]
                if "queued_at" not in queue_cols:
                    try:
                        cur.execute("ALTER TABLE label_queue ADD COLUMN queued_at TEXT")
                        conn.commit()
                    except sqlite3.OperationalError:
                        pass  # kolumna już istnieje (race condition z innym workerem)
                if "status" not in queue_cols:
                    try:
                        cur.execute(
                            "ALTER TABLE label_queue ADD COLUMN status TEXT DEFAULT 'queued'"
                        )
                        conn.commit()
                    except sqlite3.OperationalError:
                        pass  # kolumna już istnieje (race condition z innym workerem)
                if "retry_count" not in queue_cols:
                    try:
                        cur.execute(
                            "ALTER TABLE label_queue ADD COLUMN retry_count INTEGER DEFAULT 0"
                        )
                        conn.commit()
                    except sqlite3.OperationalError:
                        pass  # kolumna już istnieje (race condition z innym workerem)
                conn.commit()
            except sqlite3.OperationalError as exc:
                if self._handle_readonly_error("database migrations", exc):
                    return
                raise

            # clean entries where product name was replaced with customer name
            try:
                cur.execute("SELECT order_id, last_order_data FROM printed_orders")
                rows = cur.fetchall()
                for oid, data_json in rows:
                    try:
                        data = json.loads(data_json) if data_json else {}
                    except Exception:  # pragma: no cover - defensive
                        continue
                    name = (data.get("name") or "").strip()
                    cust = (data.get("customer") or "").strip()
                    if name and cust and name == cust:
                        prod_name, size, color = parse_product_info(
                            (data.get("products") or [{}])[0]
                        )
                        data["name"] = prod_name
                        data["size"] = size
                        data["color"] = color
                        cur.execute(
                            "UPDATE printed_orders SET last_order_data=? WHERE order_id=?",
                            (json.dumps(data), oid),
                        )
                conn.commit()
            except sqlite3.OperationalError as exc:
                if self._handle_readonly_error("printed order cleanup", exc):
                    return
                raise
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error("Błąd migracji last_order_data: %s", exc)
        finally:
            conn.close()

    def ensure_db_init(self) -> None:
        self.ensure_db()

    def load_printed_orders(self) -> List[Dict[str, Any]]:
        self.ensure_db()
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        cur.execute(
            "SELECT order_id, printed_at, last_order_data FROM printed_orders ORDER BY printed_at DESC"
        )
        rows = cur.fetchall()
        conn.close()
        items: List[Dict[str, Any]] = []
        for oid, ts, data_json in rows:
            try:
                data = json.loads(data_json) if data_json else {}
            except Exception:  # pragma: no cover - defensive
                data = {}
            items.append(
                {
                    "order_id": oid,
                    "printed_at": datetime.fromisoformat(ts),
                    "last_order_data": data,
                }
            )
        return items

    def mark_as_printed(
        self, order_id: str, last_order_data: Optional[Dict[str, Any]] = None
    ) -> None:
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        try:
            data_json = json.dumps(last_order_data or {})
            cur.execute(
                "INSERT OR IGNORE INTO printed_orders(order_id, printed_at, last_order_data) VALUES (?, ?, ?)",
                (order_id, datetime.now().isoformat(), data_json),
            )
            cur.execute(
                "UPDATE printed_orders SET last_order_data=? WHERE order_id=?",
                (data_json, order_id),
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if self._handle_readonly_error("mark_as_printed", exc):
                return
            raise
        finally:
            conn.close()
        
        # Also update order status in orders table
        try:
            from .orders import add_order_status
            from .db import get_session
            with get_session() as db:
                add_order_status(
                    db, order_id, "wydrukowano",
                    courier_code=last_order_data.get("courier_code") if last_order_data else None,
                    tracking_number=last_order_data.get("delivery_package_nr") if last_order_data else None,
                )
                db.commit()
        except Exception as status_exc:
            self.logger.warning(
                "Could not update order status for %s: %s", order_id, status_exc
            )

    def _load_state_value(self, key: str) -> Optional[str]:
        self.ensure_db()
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        cur.execute("SELECT value FROM agent_state WHERE key=?", (key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None

    def _save_state_value(self, key: str, value: Optional[str]) -> None:
        self.ensure_db()
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        try:
            if value is None:
                cur.execute("DELETE FROM agent_state WHERE key=?", (key,))
            else:
                cur.execute(
                    "INSERT INTO agent_state(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if self._handle_readonly_error("save agent state", exc):
                return
            raise
        finally:
            conn.close()

    def load_last_success_marker(self) -> SuccessMarker:
        return SuccessMarker(
            order_id=self._load_state_value("last_success_order_id"),
            timestamp=self._load_state_value("last_success_timestamp"),
        )

    def update_last_success_marker(
        self, order_id: Optional[str], timestamp: Optional[str] = None
    ) -> None:
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        self._save_state_value("last_success_timestamp", timestamp)
        if order_id is not None:
            self._save_state_value("last_success_order_id", order_id)

    def clean_old_printed_orders(self) -> None:
        threshold = datetime.now() - timedelta(days=self.config.printed_expiry_days)
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM printed_orders WHERE printed_at < ?",
                (threshold.isoformat(),),
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if self._handle_readonly_error("clean_old_printed_orders", exc):
                return
            raise
        finally:
            conn.close()

    def _deduplicate_queue(self, queue: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items = list(queue)
        seen: set[tuple] = set()
        unique: List[Dict[str, Any]] = []
        for item in items:
            # Allow multiple labels per order (multi-package). Only drop exact duplicates.
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

    def _update_queue_metrics(self, queue: Iterable[Dict[str, Any]]) -> None:
        queue_list = self._deduplicate_queue(queue)
        size = len(queue_list)
        PRINT_QUEUE_SIZE.set(size)

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
            age = max(0.0, (datetime.now() - oldest).total_seconds())
            PRINT_QUEUE_OLDEST_AGE_SECONDS.set(age)
        else:
            PRINT_QUEUE_OLDEST_AGE_SECONDS.set(0)

        return queue_list

    def load_queue(self) -> List[Dict[str, Any]]:
        self.ensure_db()
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT order_id, label_data, ext, last_order_data, queued_at, status, retry_count FROM label_queue"
            )
            rows = cur.fetchall()
        except sqlite3.OperationalError as exc:
            if "no such column" in str(exc).lower():
                cur.execute(
                    "SELECT order_id, label_data, ext, last_order_data, queued_at, status FROM label_queue"
                )
                rows = cur.fetchall()
            else:
                conn.close()
                raise
        conn.close()
        items: List[Dict[str, Any]] = []
        for row in rows:
            order_id, label_data, ext, last_order_json, queued_at, status = row[:6]
            retry_count = row[6] if len(row) > 6 else 0
            try:
                last_data = json.loads(last_order_json) if last_order_json else {}
            except Exception:  # pragma: no cover - defensive
                last_data = {}
            if not queued_at:
                queued_at = datetime.now().isoformat()
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
        deduped = self._deduplicate_queue(items)
        if len(deduped) != len(items):
            self.logger.info(
                "Removed %s duplicate queue entries from storage",
                len(items) - len(deduped),
            )
            self.save_queue(deduped)
        return deduped

    def save_queue(self, items: Iterable[Dict[str, Any]]) -> None:
        items_list = self._update_queue_metrics(items)

        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM label_queue")
            for item in items_list:
                cur.execute(
                    "INSERT INTO label_queue(order_id, label_data, ext, last_order_data, queued_at, status, retry_count)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.get("order_id"),
                        item.get("label_data"),
                        item.get("ext"),
                        json.dumps(item.get("last_order_data", {})),
                        item.get("queued_at"),
                        item.get("status", "queued"),
                        item.get("retry_count", 0),
                    ),
                )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if self._handle_readonly_error("save_queue", exc):
                return
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # External integrations
    # ------------------------------------------------------------------
    def _maybe_log_api_summary(self) -> None:
        now = datetime.now()
        if now - self._last_api_log >= timedelta(hours=1) and self._api_calls_total:
            self.logger.info(
                "Udane połączenia: [%s/%s]",
                self._api_calls_success,
                self._api_calls_total,
            )
            self._api_calls_total = 0
            self._api_calls_success = 0
            self._last_api_log = now

    def _enforce_rate_limit(self) -> None:
        max_calls = max(0, self.config.api_rate_limit_calls)
        window = self.config.api_rate_limit_period
        if max_calls <= 0 or window <= 0:
            return
        with self._rate_limit_lock:
            now = time.monotonic()
            while self._api_call_times and now - self._api_call_times[0] >= window:
                self._api_call_times.popleft()
            if len(self._api_call_times) >= max_calls:
                wait_until = self._api_call_times[0] + window
                wait_time = wait_until - now
                if wait_time > 0:
                    self.logger.debug(
                        "Rate limit reached, waiting %.2fs before next API call",
                        wait_time,
                    )
                    PRINT_AGENT_DOWNTIME_SECONDS.inc(wait_time)
                    if self._stop_event.wait(wait_time):
                        raise ApiError("Rate limit wait interrupted")
                now = time.monotonic()
                while self._api_call_times and now - self._api_call_times[0] >= window:
                    self._api_call_times.popleft()
            self._api_call_times.append(time.monotonic())

    def get_orders(self) -> List[Dict[str, Any]]:
        """Pobierz zamowienia gotowe do druku z lokalnej bazy danych.

        Szuka zamowien w statusie 'pobrano' (nowe z Allegro Events API),
        ktore nie zostaly jeszcze wydrukowane.
        """
        from .db import get_session
        from .models import Order, OrderStatusLog, OrderProduct
        from sqlalchemy import desc

        orders = []
        try:
            with get_session() as db:
                # Pobierz zamowienia z ostatnich 7 dni
                week_ago = int((datetime.now() - timedelta(days=7)).timestamp())

                recent_orders = (
                    db.query(Order)
                    .filter(Order.date_add >= week_ago)
                    .all()
                )

                for order in recent_orders:
                    # Sprawdz aktualny status
                    latest = (
                        db.query(OrderStatusLog)
                        .filter(OrderStatusLog.order_id == order.order_id)
                        .order_by(desc(OrderStatusLog.timestamp))
                        .first()
                    )
                    current_status = latest.status if latest else "pobrano"

                    # Interesuja nas tylko zamowienia w statusie 'pobrano'
                    if current_status != "pobrano":
                        continue

                    # Pobierz produkty
                    products_list = []
                    for op in order.products:
                        products_list.append({
                            "name": op.name or "",
                            "quantity": op.quantity or 1,
                            "price_brutto": str(op.price_brutto) if op.price_brutto else "0",
                            "auction_id": op.auction_id or "",
                            "sku": op.sku or "",
                            "ean": op.ean or "",
                            "attributes": op.attributes or "",
                        })

                    orders.append({
                        "order_id": order.order_id,
                        "external_order_id": order.external_order_id or "",
                        "shop_order_id": order.shop_order_id,
                        "delivery_fullname": order.delivery_fullname or "",
                        "email": order.email or "",
                        "phone": order.phone or "",
                        "user_login": order.user_login or "",
                        "order_source": order.platform or "allegro",
                        "order_source_id": order.order_source_id,
                        "order_status_id": order.order_status_id,
                        "confirmed": order.confirmed,
                        "date_add": order.date_add,
                        "date_confirmed": order.date_confirmed,
                        "date_in_status": order.date_in_status,
                        "delivery_method": order.delivery_method or "",
                        "delivery_method_id": order.delivery_method_id,
                        "delivery_price": float(order.delivery_price) if order.delivery_price else 0,
                        "delivery_company": order.delivery_company or "",
                        "delivery_address": order.delivery_address or "",
                        "delivery_city": order.delivery_city or "",
                        "delivery_postcode": order.delivery_postcode or "",
                        "delivery_country": order.delivery_country or "",
                        "delivery_country_code": order.delivery_country_code or "",
                        "delivery_point_id": order.delivery_point_id or "",
                        "delivery_point_name": order.delivery_point_name or "",
                        "delivery_point_address": order.delivery_point_address or "",
                        "delivery_point_postcode": order.delivery_point_postcode or "",
                        "delivery_point_city": order.delivery_point_city or "",
                        "invoice_fullname": order.invoice_fullname or "",
                        "invoice_company": order.invoice_company or "",
                        "invoice_nip": order.invoice_nip or "",
                        "invoice_address": order.invoice_address or "",
                        "invoice_city": order.invoice_city or "",
                        "invoice_postcode": order.invoice_postcode or "",
                        "invoice_country": order.invoice_country or "",
                        "want_invoice": order.want_invoice or "0",
                        "currency": order.currency or "PLN",
                        "payment_method": order.payment_method or "",
                        "payment_method_cod": order.payment_method_cod or "0",
                        "payment_done": order.payment_done,
                        "user_comments": order.user_comments or "",
                        "admin_comments": order.admin_comments or "",
                        "courier_code": order.courier_code or "",
                        "delivery_package_module": order.delivery_package_module or "",
                        "delivery_package_nr": order.delivery_package_nr or "",
                        "products": products_list,
                    })

                self.logger.debug("Znaleziono %d zamowien do druku", len(orders))
        except Exception as exc:
            self.logger.error("Blad pobierania zamowien z bazy: %s", exc)
            raise ApiError(str(exc)) from exc

        return orders

    def get_order_packages(self, order_id: str) -> List[Dict[str, Any]]:
        """Pobierz przesylki dla zamowienia z Allegro Shipment Management API.

        Jezeli przesylka nie istnieje, tworzy ja automatycznie
        przez create_shipment().
        """
        # Wyciagnij checkout_form_id z order_id (format: allegro_{uuid})
        checkout_form_id = order_id
        if order_id.startswith("allegro_"):
            checkout_form_id = order_id[len("allegro_"):]

        # Najpierw sprawdz czy przesylka juz istnieje w Allegro
        from .allegro_api.fulfillment import get_shipment_tracking_numbers
        try:
            existing = get_shipment_tracking_numbers(checkout_form_id)
            if existing:
                # Przesylka juz istnieje - zwroc dane
                packages = []
                for ship in existing:
                    packages.append({
                        "shipment_id": ship.get("id"),
                        "waybill": ship.get("waybill"),
                        "carrier_id": ship.get("carrierId"),
                        "courier_code": ship.get("carrierId", ""),
                        "courier_package_nr": ship.get("waybill", ""),
                    })
                return packages
        except Exception as exc:
            self.logger.debug(
                "Nie mozna sprawdzic istniejacych przesylek dla %s: %s",
                order_id, exc,
            )

        # Przesylka nie istnieje - utworz nowa przez Shipment Management
        return self._create_allegro_shipment(order_id, checkout_form_id)

    def _create_allegro_shipment(
        self, order_id: str, checkout_form_id: str,
    ) -> List[Dict[str, Any]]:
        """Utworz przesylke w Allegro Shipment Management i zwroc dane."""
        order_data = self.last_order_data
        if not order_data or order_data.get("order_id") != order_id:
            self.logger.error("Brak danych zamowienia %s do utworzenia przesylki", order_id)
            return []

        # Mapuj metode dostawy na delivery_service_id
        delivery_method = order_data.get("delivery_method", "") or order_data.get("shipping", "")
        delivery_service_id = self._resolve_delivery_service_id(delivery_method)

        if not delivery_service_id:
            self.logger.error(
                "Nie mozna ustalic delivery_service_id dla metody '%s' (zamowienie %s)",
                delivery_method, order_id,
            )
            return []

        # Dane nadawcy z ustawien
        from .settings_store import settings_store
        sender = {
            "name": settings_store.get("SENDER_NAME") or "Retriever Shop",
            "street": settings_store.get("SENDER_STREET") or "",
            "city": settings_store.get("SENDER_CITY") or "",
            "zipCode": settings_store.get("SENDER_ZIPCODE") or "",
            "countryCode": "PL",
            "phone": settings_store.get("SENDER_PHONE") or "",
            "email": settings_store.get("SENDER_EMAIL") or "",
        }

        # Dane odbiorcy z zamowienia
        receiver = {
            "name": order_data.get("delivery_fullname", ""),
            "street": order_data.get("delivery_address", ""),
            "city": order_data.get("delivery_city", ""),
            "zipCode": order_data.get("delivery_postcode", ""),
            "countryCode": order_data.get("delivery_country_code", "PL"),
            "phone": order_data.get("phone", ""),
            "email": order_data.get("email", ""),
        }

        # Punkt odbioru (paczkomat itp.)
        point_id = order_data.get("delivery_point_id", "")
        if point_id:
            receiver["pickupPointId"] = point_id

        # Domyslna paczka
        packages = [
            {
                "weight": {"value": 1.0, "unit": "KILOGRAM"},
                "dimensions": {
                    "length": {"value": 30, "unit": "CENTIMETER"},
                    "width": {"value": 20, "unit": "CENTIMETER"},
                    "height": {"value": 10, "unit": "CENTIMETER"},
                },
            }
        ]

        try:
            result = create_shipment(
                checkout_form_id=checkout_form_id,
                delivery_service_id=delivery_service_id,
                sender=sender,
                receiver=receiver,
                packages=packages,
            )

            shipment_id = result.get("id")
            waybill = ""
            # Wyciagnij waybill z packages
            for pkg in result.get("packages", []):
                waybill = pkg.get("waybill", "")
                if waybill:
                    break

            # Dodaj tracking do zamowienia w Allegro
            carrier_id = self._resolve_carrier_id(delivery_method)
            if waybill and carrier_id:
                try:
                    add_shipment_tracking(
                        checkout_form_id,
                        carrier_id=carrier_id,
                        waybill=waybill,
                    )
                except Exception as track_exc:
                    self.logger.warning(
                        "Nie mozna dodac trackingu %s do zamowienia %s: %s",
                        waybill, order_id, track_exc,
                    )

            # Zmien status fulfillment na PROCESSING
            try:
                update_fulfillment_status(checkout_form_id, "PROCESSING")
            except Exception as ful_exc:
                self.logger.warning(
                    "Nie mozna zmienic statusu fulfillment dla %s: %s",
                    order_id, ful_exc,
                )

            self.logger.info(
                "Utworzono przesylke %s (waybill: %s) dla zamowienia %s",
                shipment_id, waybill, order_id,
            )

            return [{
                "shipment_id": shipment_id,
                "waybill": waybill,
                "carrier_id": carrier_id or "",
                "courier_code": carrier_id or "",
                "courier_package_nr": waybill,
            }]

        except Exception as exc:
            self.logger.error(
                "Blad tworzenia przesylki dla zamowienia %s: %s", order_id, exc,
            )
            return []

    def _resolve_delivery_service_id(self, delivery_method: str) -> Optional[str]:
        """Mapuj nazwe metody dostawy Allegro na delivery_service_id."""
        if not delivery_method:
            return None

        method_lower = delivery_method.lower()

        try:
            services = get_delivery_services()
        except Exception as exc:
            self.logger.error("Blad pobierania delivery services: %s", exc)
            return None

        # Szukaj dokladnego dopasowania po nazwie
        for svc in services:
            svc_name = (svc.get("name") or "").lower()
            if svc_name == method_lower:
                return svc.get("id")

        # Szukaj czesciowego dopasowania
        for svc in services:
            svc_name = (svc.get("name") or "").lower()
            if method_lower in svc_name or svc_name in method_lower:
                return svc.get("id")

        self.logger.warning(
            "Nie znaleziono delivery_service_id dla '%s' "
            "wsrod %d dostepnych uslug", delivery_method, len(services),
        )
        return None

    def _resolve_carrier_id(self, delivery_method: str) -> Optional[str]:
        """Mapuj nazwe metody dostawy na carrier_id Allegro."""
        if not delivery_method:
            return None

        method_lower = delivery_method.lower()

        carrier_map = {
            "inpost": "INPOST",
            "paczkomat": "INPOST",
            "dhl": "DHL",
            "dpd": "DPD",
            "poczta": "POCZTA_POLSKA",
            "pocztex": "POCZTA_POLSKA",
            "ups": "UPS",
            "gls": "GLS",
            "fedex": "FEDEX",
            "orlen": "ALLEGRO",
            "allegro one": "ALLEGRO",
            "allegro kurier": "ALLEGRO",
            "allegro automat": "ALLEGRO",
        }

        for key, carrier_id in carrier_map.items():
            if key in method_lower:
                return carrier_id

        return "OTHER"

    def get_label(self, courier_code: str, package_id: str) -> Tuple[str, str]:
        """Pobierz etykiete przesylki z Allegro Shipment Management API.

        Args:
            courier_code: Nieuzywane (kompatybilnosc wsteczna).
            package_id: ID przesylki (shipment_id) z Allegro.

        Returns:
            Tuple (base64_label_data, extension).
        """
        if not package_id:
            raise ApiError("Brak ID przesylki do pobrania etykiety")

        try:
            label_bytes = get_shipment_label(package_id, label_format="PDF")
            label_b64 = base64.b64encode(label_bytes).decode("ascii")
            return label_b64, "pdf"
        except RuntimeError as exc:
            # Etykieta nie gotowa - sprobuj ponownie po chwili
            self.logger.warning("Etykieta nie gotowa dla %s: %s", package_id, exc)
            time.sleep(3)
            try:
                label_bytes = get_shipment_label(package_id, label_format="PDF")
                label_b64 = base64.b64encode(label_bytes).decode("ascii")
                return label_b64, "pdf"
            except Exception as retry_exc:
                raise ApiError(f"Etykieta niedostepna: {retry_exc}") from retry_exc
        except Exception as exc:
            raise ApiError(f"Blad pobierania etykiety: {exc}") from exc

    def print_label(self, base64_data: str, extension: str, order_id: str) -> None:
        file_path = f"/tmp/label_{order_id}.{extension}"
        try:
            pdf_data = base64.b64decode(base64_data)
            with open(file_path, "wb") as handle:
                handle.write(pdf_data)
            cmd = ["lp"]
            host = None
            if self.config.cups_server or self.config.cups_port:
                server = self.config.cups_server or "localhost"
                host = (
                    f"{server}:{self.config.cups_port}"
                    if self.config.cups_port
                    else server
                )
            if host:
                cmd.extend(["-h", host])
            cmd.extend(["-d", self.config.printer_name, file_path])
            result = subprocess.run(cmd, capture_output=True, check=False)
            if result.returncode != 0:
                message = result.stderr.decode().strip()
                self.logger.error(
                    "Błąd drukowania (kod %s): %s",
                    result.returncode,
                    message,
                )
                PRINT_LABEL_ERRORS_TOTAL.labels(stage="print").inc()
                raise PrintError(message or str(result.returncode))
            self.logger.info("📨 Label printed")
            PRINT_LABELS_TOTAL.inc()
        except PrintError:
            raise
        except Exception as exc:
            self.logger.error("Błąd drukowania: %s", exc)
            PRINT_LABEL_ERRORS_TOTAL.labels(stage="print").inc()
            raise PrintError(str(exc)) from exc
        finally:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:  # pragma: no cover - defensive
                pass

    def print_test_page(self) -> bool:
        try:
            file_path = "/tmp/print_test.txt"
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write("=== TEST PRINT ===\n")
            result = subprocess.run(
                ["lp", "-d", self.config.printer_name, file_path],
                capture_output=True,
                check=False,
            )
            os.remove(file_path)
            if result.returncode != 0:
                self.logger.error(
                    "Błąd testowego druku (kod %s): %s",
                    result.returncode,
                    result.stderr.decode().strip(),
                )
                return False
            self.logger.info("🔧 Testowa strona została wysłana do drukarki.")
            return True
        except Exception as exc:
            self.logger.error("Błąd testowego druku: %s", exc)
            return False

    def _should_send_error_notification(self, order_id: str) -> bool:
        """Sprawdza czy należy wysłać powiadomienie o błędzie (przy próbie 1 i 10)."""
        count = self._label_error_notifications.get(order_id, 0)
        return count == 0 or count == 9  # 0 = pierwsza próba, 9 = dziesiąta próba

    def _send_label_error_notification(self, order_id: str) -> None:
        """Wysyła krótkie powiadomienie o braku etykiety."""
        try:
            message = f"Brak etykiety do zamówienia nr: {order_id}"
            response = requests.post(
                "https://graph.facebook.com/v17.0/me/messages",
                headers={
                    "Authorization": f"Bearer {self.config.page_access_token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(
                    {
                        "recipient": {"id": self.config.recipient_id},
                        "message": {"text": message},
                    }
                ),
                timeout=10,
            )
            response.raise_for_status()
            # Inkrementuj licznik
            self._label_error_notifications[order_id] = self._label_error_notifications.get(order_id, 0) + 1
        except Exception as exc:
            self.logger.error("Błąd wysyłania wiadomości: %s", exc)

    def send_messenger_message(self, data: Dict[str, Any], print_success: bool = True) -> None:
        try:
            # Status etykiety
            if print_success:
                label_status = "✅ Etykieta gotowa"
            else:
                label_status = "❌ Błąd drukowania etykiety"

            message = (
                f"📦 Nowe zamówienie od: {data.get('customer', '-')}\n"
                f"🛒 Produkty:\n"
                + "".join(
                    f"- {p['name']} (x{p['quantity']})\n"
                    for p in data.get("products", [])
                )
                + f"🚚 Wysyłka: {data.get('shipping', '-')}\n"
                f"🚛 Kurier: {data.get('courier_code', '-')}\n"
                f"🌐 Platforma: {data.get('platform', '-')}\n"
                f"📎 ID: {data.get('order_id', '-')}\n"
                f"🏷️ {label_status}"
            )

            response = requests.post(
                "https://graph.facebook.com/v17.0/me/messages",
                headers={
                    "Authorization": f"Bearer {self.config.page_access_token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(
                    {
                        "recipient": {"id": self.config.recipient_id},
                        "message": {"text": message},
                    }
                ),
                timeout=10,
            )
            response.raise_for_status()
        except Exception as exc:
            self.logger.error("Błąd wysyłania wiadomości: %s", exc)

    # ------------------------------------------------------------------
    # Tracking status updates (Allegro API)
    # ------------------------------------------------------------------
    # Allegro tracking event type -> our internal status
    ALLEGRO_TRACKING_STATUS_MAP = {
        "DELIVERED": "dostarczono",
        "READY_FOR_PICKUP": "gotowe_do_odbioru",
        "PICKED_UP": "dostarczono",
        "SENT": "przekazano_kurierowi",
        "PICKED_UP_BY_CARRIER": "przekazano_kurierowi",
        "IN_TRANSIT": "w_drodze",
        "OUT_FOR_DELIVERY": "w_drodze",
        "RETURNED": "zwrot",
        "RETURNED_TO_SENDER": "zwrot",
        "CANCELLED": "anulowano",
        "LOST": "zagubiono",
        "FAILED_DELIVERY": "niedostarczono",
        "LABEL_CREATED": "wydrukowano",
    }

    def _check_tracking_statuses(self) -> None:
        """Sprawdz i zaktualizuj statusy przesylek przez Allegro Tracking API."""
        try:
            from .orders import add_order_status
            from .db import get_session
            from .models import Order, OrderStatusLog
            from .allegro_api.tracking import fetch_parcel_tracking
            from .settings_store import settings_store
            from sqlalchemy import desc

            access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
            if not access_token:
                self.logger.debug("Brak tokenu Allegro - pomijam sprawdzanie trackingu")
                return

            with get_session() as db:
                from datetime import datetime, timedelta
                week_ago = int((datetime.now() - timedelta(days=7)).timestamp())

                orders_to_check = (
                    db.query(Order)
                    .filter(Order.date_add >= week_ago)
                    .all()
                )

                if not orders_to_check:
                    return

                # Zbierz zamowienia z waybill pogrupowane po carrier
                carrier_waybills: Dict[str, List[Tuple[Order, str, str]]] = {}
                for order in orders_to_check:
                    latest_status = (
                        db.query(OrderStatusLog)
                        .filter(OrderStatusLog.order_id == order.order_id)
                        .order_by(desc(OrderStatusLog.timestamp))
                        .first()
                    )
                    current_status = latest_status.status if latest_status else "niewydrukowano"

                    if current_status in ("dostarczono", "zwrot", "zagubiono", "anulowano", "zakończono"):
                        continue

                    waybill = order.delivery_package_nr
                    if not waybill:
                        continue

                    carrier_id = self._resolve_carrier_id(
                        order.delivery_method or order.delivery_package_module or ""
                    ) or "OTHER"

                    carrier_waybills.setdefault(carrier_id, []).append(
                        (order, waybill, current_status)
                    )

                self.logger.debug(
                    "Sprawdzam tracking dla %d zamowien (%d przewoznikow)",
                    sum(len(v) for v in carrier_waybills.values()),
                    len(carrier_waybills),
                )

                # Odpytaj Allegro Tracking API per carrier (max 20 waybilli per request)
                for carrier_id, order_items in carrier_waybills.items():
                    waybill_to_order = {item[1]: (item[0], item[2]) for item in order_items}
                    waybill_list = list(waybill_to_order.keys())

                    # Podziel na batche po 20
                    for i in range(0, len(waybill_list), 20):
                        batch = waybill_list[i:i + 20]
                        try:
                            tracking_data = fetch_parcel_tracking(
                                access_token, carrier_id, batch
                            )
                        except Exception as exc:
                            self.logger.warning(
                                "Blad pobierania trackingu %s: %s", carrier_id, exc
                            )
                            continue

                        for wb_data in tracking_data.get("waybills", []):
                            waybill = wb_data.get("waybill", "")
                            if waybill not in waybill_to_order:
                                continue

                            order_obj, current_status = waybill_to_order[waybill]
                            events = wb_data.get("events", [])
                            if not events:
                                continue

                            # Najnowszy event (pierwszy na liscie)
                            latest_event = events[0]
                            event_type = latest_event.get("type", "")
                            new_status = self.ALLEGRO_TRACKING_STATUS_MAP.get(event_type)

                            if not new_status or new_status == current_status:
                                continue

                            self.logger.info(
                                "Zmiana statusu zamowienia %s: %s -> %s (event: %s)",
                                order_obj.order_id, current_status, new_status, event_type,
                            )

                            try:
                                add_order_status(
                                    db, order_obj.order_id, new_status,
                                    tracking_number=waybill,
                                    courier_code=carrier_id,
                                    notes=f"Auto-update z Allegro Tracking ({event_type})",
                                )
                                db.commit()
                            except Exception as status_exc:
                                self.logger.warning(
                                    "Blad aktualizacji statusu %s: %s",
                                    order_obj.order_id, status_exc,
                                )
                                db.rollback()

        except Exception as exc:
            self.logger.warning("Blad sprawdzania statusow przesylek: %s", exc)

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------
    def is_quiet_time(self) -> bool:
        now = datetime.now(ZoneInfo(self.config.timezone)).time()
        start = self.config.quiet_hours_start
        end = self.config.quiet_hours_end
        if start <= end:
            return start <= now < end
        return now >= start or now < end

    def _send_periodic_reports(self) -> None:
        """Wysyła raporty tygodniowe i miesięczne przez Messenger.
        
        Format raportu:
        - Tygodniowy: "W tym tygodniu sprzedałaś [ilość] produktów za [suma] zł co dało [zysk] zł zysku"
        - Miesięczny: "W miesiącu [nazwa] sprzedałaś [ilość] produktów za [suma] zł co dało [zysk] zł zysku"
        """
        from datetime import datetime, timedelta
        from decimal import Decimal
        
        now = datetime.now()
        
        # Wysylka raportu tygodniowego - co 7 dni
        if self.config.enable_weekly_reports and (
            not hasattr(self, "_last_weekly_report")
            or not self._last_weekly_report
            or now - self._last_weekly_report >= timedelta(days=7)
        ):
            summary = self._get_period_summary(days=7)
            if summary:
                message = (
                    f"W tym tygodniu sprzedałaś {summary['products_sold']} produktów "
                    f"za {summary['total_revenue']:.2f} zł co dało {summary['real_profit']:.2f} zł zysku"
                )
                send_report("Raport tygodniowy", [message])
                self._last_weekly_report = now
        
        # Wysylka raportu miesiecznego - 1. dnia miesiaca za poprzedni miesiac
        if self.config.enable_monthly_reports:
            # Sprawdz czy jest 1. dzien miesiaca i czy raport za poprzedni miesiac juz wyslany
            is_first_day = now.day == 1
            last_report_month = getattr(self, "_last_monthly_report_month", None)
            
            if is_first_day and last_report_month != (now.year, now.month):
                # Pobierz dane za poprzedni miesiac
                prev_month_end = (now.replace(day=1) - timedelta(days=1))
                prev_month_start = prev_month_end.replace(day=1)
                days_in_prev_month = (prev_month_end - prev_month_start).days + 1
                
                MONTH_NAMES = ['Styczen', 'Luty', 'Marzec', 'Kwiecien', 'Maj', 'Czerwiec',
                               'Lipiec', 'Sierpien', 'Wrzesien', 'Pazdziernik', 'Listopad', 'Grudzien']
                month_name = MONTH_NAMES[prev_month_end.month - 1]
                
                summary = self._get_period_summary(days=days_in_prev_month, end_date=prev_month_end, include_fixed_costs=True)
                if summary:
                    # Dodaj informacje o kosztach stalych jesli sa
                    fixed_info = ""
                    if summary.get('fixed_costs', 0) > 0:
                        fixed_info = f" (po odliczeniu {summary['fixed_costs']:.0f} zł kosztów stałych)"
                    message = (
                        f"W miesiącu {month_name} sprzedałaś {summary['products_sold']} produktów "
                        f"za {summary['total_revenue']:.2f} zł co dało {summary['real_profit']:.2f} zł zysku{fixed_info}"
                    )
                    send_report("Raport miesieczny", [message])
                    self._last_monthly_report_month = (now.year, now.month)
    
    def _get_period_summary(self, days: int, end_date: datetime = None, include_fixed_costs: bool = False) -> dict:
        """Pobiera podsumowanie sprzedazy za okres z obliczeniem realnego zysku.
        
        Args:
            days: Liczba dni wstecz od end_date
            end_date: Data koncowa (domyslnie teraz)
            include_fixed_costs: Czy odejmowac koszty stale (dla raportow miesiecznych)
            
        Returns:
            Dict z kluczami: products_sold, total_revenue, real_profit, fixed_costs (opcjonalnie)
        """
        from datetime import datetime, timedelta
        
        if end_date is None:
            end_date = datetime.now()
        
        start_date = end_date - timedelta(days=days)
        start_ts = int(start_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        end_ts = int(end_date.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
        
        try:
            from .db import get_session
            from .domain.financial import FinancialCalculator
            from .settings_store import settings_store
            
            access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
            
            with get_session() as db:
                calculator = FinancialCalculator(db, settings_store)
                summary = calculator.get_period_summary(
                    start_ts, 
                    end_ts,
                    include_fixed_costs=include_fixed_costs,
                    access_token=access_token
                )
                
                result = {
                    "products_sold": summary.products_sold,
                    "total_revenue": float(summary.total_revenue),
                    "real_profit": float(summary.net_profit if include_fixed_costs else summary.gross_profit),
                }
                if include_fixed_costs:
                    result["profit_before_fixed"] = float(summary.gross_profit)
                    result["fixed_costs"] = float(summary.fixed_costs)
                    result["fixed_costs_list"] = summary.fixed_costs_list
                return result
                
        except Exception as e:
            self.logger.error("Blad pobierania podsumowania sprzedazy: %s", e)
            return None

    def _process_queue(self, queue: List[Dict[str, Any]], printed: Dict[str, Any]) -> List[Dict[str, Any]]:
        MAX_QUEUE_RETRIES = 10  # Maksymalna liczba prób drukowania z kolejki
        
        if self.is_quiet_time():
            return queue
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in queue:
            grouped.setdefault(item["order_id"], []).append(item)

        new_queue: List[Dict[str, Any]] = []
        for oid, items in grouped.items():
            # Sprawdź liczbę prób - każdy element ma swój licznik
            retry_count = items[0].get("retry_count", 0)
            
            if retry_count >= MAX_QUEUE_RETRIES:
                self.logger.error(
                    "Zamówienie %s przekroczyło limit %d prób drukowania - usuwam z kolejki",
                    oid, MAX_QUEUE_RETRIES
                )
                # Oznacz jako przetworzone żeby nie wracało
                self.mark_as_printed(oid, items[0].get("last_order_data"))
                # Wyślij powiadomienie o permanentnym błędzie
                self._notify_messenger(items[0].get("last_order_data", {}), print_success=False)
                continue
            
            try:
                for it in items:
                    it["status"] = "in_progress"
                self.save_queue(queue)
                for it in items:
                    self._retry(
                        self.print_label,
                        it["label_data"],
                        it.get("ext", "pdf"),
                        it["order_id"],
                        stage="print",
                        retry_exceptions=(PrintError,),
                    )
                consume_order_stock(items[0].get("last_order_data", {}).get("products", []))
                self.mark_as_printed(oid, items[0].get("last_order_data"))
                printed[oid] = datetime.now()
                # Wysyłamy powiadomienie o sukcesie z kolejki
                self._notify_messenger(items[0].get("last_order_data", {}), print_success=True)
            except Exception as exc:
                self.logger.error("Błąd przetwarzania z kolejki (próba %d/%d): %s", retry_count + 1, MAX_QUEUE_RETRIES, exc)
                for it in items:
                    it["status"] = "queued"
                    it["retry_count"] = retry_count + 1
                new_queue.extend(items)
                PRINT_LABEL_ERRORS_TOTAL.labels(stage="queue").inc()
                # NIE wysyłamy wiadomości - była już wysłana przy pierwszej próbie
                # Wiadomość zostanie wysłana tylko przy sukcesie lub przekroczeniu limitu
        return new_queue

    def _check_allegro_discussions(self, access_token: str) -> None:
        """Sprawdza dyskusje Allegro - deleguje do AllegroSyncService."""
        service = AllegroSyncService(
            db_file=self.config.db_file,
            settings=self.settings,
            save_state_callback=self._save_state_value
        )
        service.check_discussions(access_token)

    def _check_allegro_messages(self, access_token: str) -> None:
        """Sprawdza wiadomosci Allegro - deleguje do AllegroSyncService."""
        service = AllegroSyncService(
            db_file=self.config.db_file,
            settings=self.settings,
            save_state_callback=self._save_state_value
        )
        service.check_messages(access_token)

    def _agent_loop(self) -> None:
        allegro_check_interval = timedelta(minutes=5)
        tracking_check_interval = timedelta(minutes=15)
        last_allegro_check = datetime.now() - allegro_check_interval
        last_tracking_check = datetime.now() - tracking_check_interval

        while not self._stop_event.is_set():
            loop_start = datetime.now()
            self._write_heartbeat()
            self._send_periodic_reports()

            # Check tracking statuses every 15 minutes
            if datetime.now() - last_tracking_check >= tracking_check_interval:
                self._check_tracking_statuses()
                last_tracking_check = datetime.now()

            if datetime.now() - last_allegro_check >= allegro_check_interval:
                token_valid = hasattr(self.settings, 'ALLEGRO_ACCESS_TOKEN') and self.settings.ALLEGRO_ACCESS_TOKEN
                expires_at = getattr(self.settings, 'ALLEGRO_TOKEN_EXPIRES_AT', 0)

                if not token_valid or expires_at <= time.time():
                    self.logger.info("Token Allegro niedostępny lub nieważny, pomijam sprawdzanie.")
                else:
                    access_token = self.settings.ALLEGRO_ACCESS_TOKEN
                    self._check_allegro_discussions(access_token)
                    self._check_allegro_messages(access_token)
                last_allegro_check = datetime.now()

            self.clean_old_printed_orders()
            printed_entries = self.load_printed_orders()
            printed = {entry["order_id"]: entry["printed_at"] for entry in printed_entries}
            queue = self.load_queue()

            queue = self._restore_in_progress(queue)

            queue = self._process_queue(queue, printed)
            self.save_queue(queue)

            try:
                try:
                    orders = self._retry(
                        self.get_orders,
                        stage="orders",
                        retry_exceptions=(ApiError,),
                    )
                except ApiError as exc:
                    self.logger.error("Błąd pobierania zamówień: %s", exc)
                    PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
                    orders = []
                for order in orders:
                    order_id = str(order["order_id"])
                    prod_name, size, color = parse_product_info(
                        (order.get("products") or [{}])[0]
                    )
                    self.last_order_data = {
                        # Basic order info
                        "order_id": order_id,
                        "external_order_id": order.get("external_order_id", ""),
                        "shop_order_id": order.get("shop_order_id"),
                        "name": prod_name,
                        "size": size,
                        "color": color,
                        # Customer info
                        "customer": order.get("delivery_fullname", "Nieznany klient"),
                        "email": order.get("email", ""),
                        "phone": order.get("phone", ""),
                        "user_login": order.get("user_login", ""),
                        # Order source and status
                        "platform": order.get("order_source", "brak"),
                        "order_source_id": order.get("order_source_id"),
                        "order_status_id": order.get("order_status_id"),
                        "confirmed": order.get("confirmed", False),
                        # Dates (unix timestamps)
                        "date_add": order.get("date_add"),
                        "date_confirmed": order.get("date_confirmed"),
                        "date_in_status": order.get("date_in_status"),
                        # Delivery address
                        "shipping": order.get("delivery_method", "brak"),
                        "delivery_method_id": order.get("delivery_method_id"),
                        "delivery_price": order.get("delivery_price", 0),
                        "delivery_fullname": order.get("delivery_fullname", ""),
                        "delivery_company": order.get("delivery_company", ""),
                        "delivery_address": order.get("delivery_address", ""),
                        "delivery_city": order.get("delivery_city", ""),
                        "delivery_postcode": order.get("delivery_postcode", ""),
                        "delivery_country": order.get("delivery_country", ""),
                        "delivery_country_code": order.get("delivery_country_code", ""),
                        # Pickup point (paczkomat)
                        "delivery_point_id": order.get("delivery_point_id", ""),
                        "delivery_point_name": order.get("delivery_point_name", ""),
                        "delivery_point_address": order.get("delivery_point_address", ""),
                        "delivery_point_postcode": order.get("delivery_point_postcode", ""),
                        "delivery_point_city": order.get("delivery_point_city", ""),
                        # Invoice address
                        "invoice_fullname": order.get("invoice_fullname", ""),
                        "invoice_company": order.get("invoice_company", ""),
                        "invoice_nip": order.get("invoice_nip", ""),
                        "invoice_address": order.get("invoice_address", ""),
                        "invoice_city": order.get("invoice_city", ""),
                        "invoice_postcode": order.get("invoice_postcode", ""),
                        "invoice_country": order.get("invoice_country", ""),
                        "want_invoice": order.get("want_invoice", "0"),
                        # Payment
                        "currency": order.get("currency", "PLN"),
                        "payment_method": order.get("payment_method", ""),
                        "payment_method_cod": order.get("payment_method_cod", "0"),
                        "payment_done": order.get("payment_done", 0),
                        # Comments
                        "user_comments": order.get("user_comments", ""),
                        "admin_comments": order.get("admin_comments", ""),
                        # Products with EAN
                        "products": order.get("products", []),
                        # Courier/shipping tracking (filled later)
                        "courier_code": "",
                        "delivery_package_module": order.get("delivery_package_module", ""),
                        "delivery_package_nr": order.get("delivery_package_nr", ""),
                        "package_ids": [],
                        "tracking_numbers": [],
                    }

                    if order_id in printed:
                        continue

                    # Sprawdź czy zamówienie jest już w kolejce oczekującej
                    queued_order_ids = {item["order_id"] for item in queue}
                    if order_id in queued_order_ids:
                        continue

                    try:
                        packages = self._retry(
                            self.get_order_packages,
                            order_id,
                            stage="packages",
                            retry_exceptions=(ApiError,),
                        )
                    except ApiError as exc:
                        self.logger.error(
                            "Błąd pobierania paczek dla %s: %s", order_id, exc
                        )
                        PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
                        continue
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
                        try:
                            label_data, ext = self._retry(
                                self.get_label,
                                courier_code,
                                shipment_id,
                                stage="label",
                                retry_exceptions=(ApiError,),
                            )
                        except ApiError as exc:
                            self.logger.error(
                                "Blad pobierania etykiety %s/%s: %s",
                                courier_code,
                                shipment_id,
                                exc,
                            )
                            PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
                            continue
                        if label_data:
                            labels.append((label_data, ext))

                    if courier_code:
                        self.last_order_data["courier_code"] = courier_code
                    if package_ids:
                        self.last_order_data["package_ids"] = list(dict.fromkeys(package_ids))
                    if tracking_numbers:
                        self.last_order_data["tracking_numbers"] = list(dict.fromkeys(tracking_numbers))
                        # delivery_package_nr uzywany przez mark_as_printed
                        self.last_order_data["delivery_package_nr"] = tracking_numbers[0]

                    if labels:
                        if self.is_quiet_time():
                            for label_data, ext in labels:
                                queue.append(
                                    {
                                        "order_id": order_id,
                                        "label_data": label_data,
                                        "ext": ext,
                                        "last_order_data": self.last_order_data,
                                        "queued_at": datetime.now().isoformat(),
                                        "status": "queued",
                                    }
                                )
                            # W quiet_hours etykieta jest w kolejce - wysyłamy info o sukcesie
                            self._notify_messenger(self.last_order_data, print_success=True)
                            self.mark_as_printed(order_id, self.last_order_data)
                            printed[order_id] = datetime.now()
                        else:
                            entries: List[Dict[str, Any]] = []
                            for label_data, ext in labels:
                                entry = {
                                    "order_id": order_id,
                                    "label_data": label_data,
                                    "ext": ext,
                                    "last_order_data": self.last_order_data,
                                    "queued_at": datetime.now().isoformat(),
                                    "status": "in_progress",
                                }
                                queue.append(entry)
                                entries.append(entry)
                            self.save_queue(queue)
                            print_success = True
                            try:
                                for entry in entries:
                                    self._retry(
                                        self.print_label,
                                        entry["label_data"],
                                        entry.get("ext", "pdf"),
                                        entry["order_id"],
                                        stage="print",
                                        retry_exceptions=(PrintError,),
                                    )
                                consume_order_stock(
                                    self.last_order_data.get("products", [])
                                )
                                self.mark_as_printed(order_id, self.last_order_data)
                                printed[order_id] = datetime.now()
                                for entry in entries:
                                    if entry in queue:
                                        queue.remove(entry)
                            except Exception as exc:
                                self.logger.error(
                                    "Błąd drukowania zamówienia %s: %s", order_id, exc
                                )
                                print_success = False
                                for entry in entries:
                                    entry["status"] = "queued"
                                self.save_queue(queue)
                            # Zawsze wysyłaj wiadomość - z info o statusie drukowania
                            self._notify_messenger(self.last_order_data, print_success=print_success)
                    else:
                        # Brak etykiety - nie mozna utworzyc przesylki w Allegro
                        self.logger.error(
                            "Brak etykiety dla zamowienia %s (Allegro nie zwrocilo danych)",
                            order_id,
                        )
                        PRINT_LABEL_ERRORS_TOTAL.labels(stage="label").inc()
                        # Wyślij powiadomienie tylko przy 1 i 10 próbie
                        if self._should_send_error_notification(order_id):
                            self._send_label_error_notification(order_id)
                        else:
                            # Inkrementuj licznik bez wysyłania
                            self._label_error_notifications[order_id] = self._label_error_notifications.get(order_id, 0) + 1
            except Exception as exc:
                self.logger.error("[BŁĄD GŁÓWNY] %s", exc)
                PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()

            self.save_queue(queue)
            duration = (datetime.now() - loop_start).total_seconds()
            PRINT_AGENT_ITERATION_SECONDS.observe(duration)
            self._write_heartbeat()
            self._stop_event.wait(self.config.poll_interval)

    def start_agent_thread(self) -> bool:
        if self._agent_thread and self._agent_thread.is_alive():
            return False

        self._cleanup_orphaned_lock()
        if self._lock_handle is None:
            try:
                self._lock_handle = open(self.config.lock_file, "w")
                if fcntl:
                    fcntl.flock(self._lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # On Windows, skip file locking
            except OSError:
                if self._lock_handle:
                    self._lock_handle.close()
                    self._lock_handle = None
                self.logger.info("Print agent already running, skipping startup")
                return False
        self._write_heartbeat()
        self._stop_event = threading.Event()
        self._agent_thread = threading.Thread(target=self._agent_loop, daemon=True)
        self._agent_thread.start()
        return True

    def _notify_messenger(self, data: Dict[str, Any], print_success: bool) -> None:
        """Call ``send_messenger_message`` while tolerating simplified monkeypatches."""

        try:
            self.send_messenger_message(data, print_success=print_success)
        except TypeError:
            # Some tests replace the method with a one-argument stub; fall back gracefully
            self.send_messenger_message(data)


    def stop_agent_thread(self) -> None:
        if self._agent_thread and self._agent_thread.is_alive():
            self._stop_event.set()
            self._agent_thread.join()
            self._agent_thread = None
        self._clear_heartbeat()
        if self._lock_handle:
            try:
                if fcntl:
                    fcntl.flock(self._lock_handle, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - defensive
                pass
            self._lock_handle.close()
            self._lock_handle = None
            try:
                os.remove(self.config.lock_file)
            except OSError:
                pass
        token_refresher.stop()


def shorten_product_name(full_name: str) -> str:
    words = full_name.strip().split()
    if len(words) >= 3:
        return f"{words[0]} {' '.join(words[-2:])}"
    return full_name


# Instantiate default agent used throughout the application.
agent = LabelAgent(AgentConfig.from_settings(settings), settings)
logger = agent.logger


def __getattr__(name: str) -> Any:
    if hasattr(agent, name):
        return getattr(agent, name)
    lower_name = name.lower()
    if hasattr(agent.config, lower_name):
        return getattr(agent.config, lower_name)
    raise AttributeError(name)


__all__ = [
    "AgentConfig",
    "LabelAgent",
    "ConfigError",
    "ApiError",
    "PrintError",
    "agent",
    "logger",
    "parse_time_str",
    "shorten_product_name",
]
