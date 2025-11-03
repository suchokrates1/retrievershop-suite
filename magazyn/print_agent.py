from __future__ import annotations

import base64
import fcntl
import json
import logging
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, time as dt_time
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple, Type, TypeVar
from zoneinfo import ZoneInfo

import requests
import sqlite3

from magazyn import DB_PATH

from .config import load_config, settings
from .db import sqlite_connect
from .notifications import send_report
from .parsing import parse_product_info
from .services import consume_order_stock, get_sales_summary
from .allegro_token_refresher import token_refresher
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
    """Raised when the Baselinker API call fails."""


class PrintError(Exception):
    """Raised when sending data to the printer fails."""


T = TypeVar("T")


def parse_time_str(value: str) -> dt_time:
    """Return time from ``HH:MM`` or raise ``ValueError``."""
    try:
        return dt_time.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid time value: {value}") from exc


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
    base_url: str = "https://api.baselinker.com/connector.php"
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
            cups_port=cfg.CUPS_PORT,
            poll_interval=cfg.POLL_INTERVAL,
            quiet_hours_start=parse_time_str(cfg.QUIET_HOURS_START),
            quiet_hours_end=parse_time_str(cfg.QUIET_HOURS_END),
            timezone=cfg.TIMEZONE,
            printed_expiry_days=cfg.PRINTED_EXPIRY_DAYS,
            enable_weekly_reports=cfg.ENABLE_WEEKLY_REPORTS,
            enable_monthly_reports=cfg.ENABLE_MONTHLY_REPORTS,
            log_level=cfg.LOG_LEVEL,
            log_file=log_file,
            db_file=getattr(cfg, "DB_PATH", DB_PATH),
            lock_file=lock_file,
            legacy_printed_file=os.path.join(base_dir, "printed_orders.txt"),
            legacy_queue_file=os.path.join(base_dir, "queued_labels.jsonl"),
            legacy_db_file=os.path.abspath(
                os.path.join(base_dir, os.pardir, "printer", "data.db")
            ),
            api_rate_limit_calls=cfg.API_RATE_LIMIT_CALLS,
            api_rate_limit_period=cfg.API_RATE_LIMIT_PERIOD,
            api_retry_attempts=cfg.API_RETRY_ATTEMPTS,
            api_retry_backoff_initial=cfg.API_RETRY_BACKOFF_INITIAL,
            api_retry_backoff_max=cfg.API_RETRY_BACKOFF_MAX,
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
        self._headers = {
            "X-BLToken": config.api_token,
            "Content-Type": "application/x-www-form-urlencoded",
        }
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
        self._headers["X-BLToken"] = self.config.api_token
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
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
                cur.execute("PRAGMA table_info(label_queue)")
                queue_cols = [row[1] for row in cur.fetchall()]
                if "queued_at" not in queue_cols:
                    cur.execute("ALTER TABLE label_queue ADD COLUMN queued_at TEXT")
                    conn.commit()
                if "status" not in queue_cols:
                    cur.execute(
                        "ALTER TABLE label_queue ADD COLUMN status TEXT DEFAULT 'queued'"
                    )
                    conn.commit()
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
        seen: set[str] = set()
        unique: List[Dict[str, Any]] = []
        for item in items:
            order_id = item.get("order_id")
            if order_id is not None and order_id in seen:
                self.logger.debug("Dropping duplicate queue entry for %s", order_id)
                continue
            if order_id is not None:
                seen.add(order_id)
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
        cur.execute(
            "SELECT order_id, label_data, ext, last_order_data, queued_at, status FROM label_queue"
        )
        rows = cur.fetchall()
        conn.close()
        items: List[Dict[str, Any]] = []
        for order_id, label_data, ext, last_order_json, queued_at, status in rows:
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
                    "INSERT INTO label_queue(order_id, label_data, ext, last_order_data, queued_at, status)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        item.get("order_id"),
                        item.get("label_data"),
                        item.get("ext"),
                        json.dumps(item.get("last_order_data", {})),
                        item.get("queued_at"),
                        item.get("status", "queued"),
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

    def call_api(
        self,
        method: str,
        parameters: Optional[Dict[str, Any]] = None,
        *,
        raise_on_error: bool = False,
    ) -> Dict[str, Any]:
        parameters = parameters or {}
        max_attempts = max(1, self.config.api_retry_attempts)
        backoff_initial = max(0.0, self.config.api_retry_backoff_initial)
        backoff_max = max(backoff_initial, self.config.api_retry_backoff_max)
        attempts = 0
        last_error: Optional[Exception] = None

        while attempts < max_attempts and not self._stop_event.is_set():
            attempts += 1
            try:
                self._enforce_rate_limit()
            except ApiError as exc:
                last_error = exc
                self.logger.error("Rate limit error in call_api(%s): %s", method, exc)
                break

            success = False
            response_data: Dict[str, Any] = {}
            attempt_error: Optional[Exception] = None
            try:
                payload = {"method": method, "parameters": json.dumps(parameters)}
                response = requests.post(
                    self.config.base_url,
                    headers=self._headers,
                    data=payload,
                    timeout=10,
                )
                response.raise_for_status()
                response_data = response.json()
                success = True
            except requests.exceptions.HTTPError as exc:
                attempt_error = exc
                last_error = exc
                self.logger.error("HTTP error in call_api(%s): %s", method, exc)
            except requests.exceptions.RequestException as exc:
                attempt_error = exc
                last_error = exc
                self.logger.error("Request error in call_api(%s): %s", method, exc)
            except Exception as exc:  # pragma: no cover - defensive
                attempt_error = exc
                last_error = exc
                self.logger.error("Błąd w call_api(%s): %s", method, exc)
            finally:
                self._api_calls_total += 1
                if success:
                    self._api_calls_success += 1
                self._maybe_log_api_summary()

            if success:
                return response_data

            if attempts >= max_attempts:
                break

            delay = backoff_initial * (2 ** (attempts - 1))
            if delay > backoff_max:
                delay = backoff_max
            if delay > 0 and attempt_error is not None:
                self.logger.warning(
                    "call_api(%s) retrying in %.1fs (attempt %s/%s)",
                    method,
                    delay,
                    attempts + 1,
                    max_attempts,
                )
                PRINT_AGENT_RETRIES_TOTAL.inc()
                PRINT_AGENT_DOWNTIME_SECONDS.inc(delay)
                if self._stop_event.wait(delay):
                    break

        if raise_on_error and last_error is not None:
            raise ApiError(str(last_error)) from last_error
        return {}

    def get_orders(self) -> List[Dict[str, Any]]:
        marker = self.load_last_success_marker()
        params: Dict[str, Any] = {
            "status_id": self.config.status_id,
            "include_products": 1,
        }
        if marker.order_id:
            params["last_success_order_id"] = marker.order_id
        if marker.timestamp:
            params["last_success_timestamp"] = marker.timestamp
        response = self.call_api("getOrders", params, raise_on_error=True)
        orders = response.get("orders", [])
        last_seen = marker.order_id
        for order in orders:
            order_id = order.get("order_id")
            if order_id is not None:
                last_seen = str(order_id)
        self.update_last_success_marker(last_seen)
        return orders

    def get_order_packages(self, order_id: str) -> List[Dict[str, Any]]:
        response = self.call_api(
            "getOrderPackages",
            {"order_id": order_id},
            raise_on_error=True,
        )
        return response.get("packages", [])

    def get_label(self, courier_code: str, package_id: str) -> Tuple[str, str]:
        response = self.call_api(
            "getLabel",
            {"courier_code": courier_code, "package_id": package_id},
            raise_on_error=True,
        )
        return response.get("label"), response.get("extension", "pdf")

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

    def send_messenger_message(self, data: Dict[str, Any]) -> None:
        try:
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
                f"📎 ID: {data.get('order_id', '-')}"
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
        now = datetime.now()
        if self.config.enable_weekly_reports and (
            not hasattr(self, "_last_weekly_report")
            or not self._last_weekly_report
            or now - self._last_weekly_report >= timedelta(days=7)
        ):
            report = get_sales_summary(7)
            lines = [
                f"- {r['name']} {r['size']}: sprzedano {r['sold']}, zostalo {r['remaining']}"
                for r in report
            ]
            send_report("Raport tygodniowy", lines)
            self._last_weekly_report = now
        if self.config.enable_monthly_reports and (
            not hasattr(self, "_last_monthly_report")
            or not self._last_monthly_report
            or now - self._last_monthly_report >= timedelta(days=30)
        ):
            report = get_sales_summary(30)
            lines = [
                f"- {r['name']} {r['size']}: sprzedano {r['sold']}, zostalo {r['remaining']}"
                for r in report
            ]
            send_report("Raport miesieczny", lines)
            self._last_monthly_report = now

    def _process_queue(self, queue: List[Dict[str, Any]], printed: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.is_quiet_time():
            return queue
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in queue:
            grouped.setdefault(item["order_id"], []).append(item)

        new_queue: List[Dict[str, Any]] = []
        for oid, items in grouped.items():
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
            except Exception as exc:
                self.logger.error("Błąd przetwarzania z kolejki: %s", exc)
                for it in items:
                    it["status"] = "queued"
                new_queue.extend(items)
                PRINT_LABEL_ERRORS_TOTAL.labels(stage="queue").inc()
        return new_queue

    def _agent_loop(self) -> None:
        while not self._stop_event.is_set():
            loop_start = datetime.now()
            self._write_heartbeat()
            self._send_periodic_reports()
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
                        "order_id": order_id,
                        "name": prod_name,
                        "size": size,
                        "color": color,
                        "customer": order.get("delivery_fullname", "Nieznany klient"),
                        "platform": order.get("order_source", "brak"),
                        "shipping": order.get("delivery_method", "brak"),
                        "products": order.get("products", []),
                        "courier_code": "",
                    }

                    if order_id in printed:
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

                    for package in packages:
                        package_id = package.get("package_id")
                        code = package.get("courier_code")
                        if code and not courier_code:
                            courier_code = code
                        if not package_id or not code:
                            self.logger.warning("  Brak danych: package_id lub courier_code")
                            continue
                        try:
                            label_data, ext = self._retry(
                                self.get_label,
                                courier_code,
                                package_id,
                                stage="label",
                                retry_exceptions=(ApiError,),
                            )
                        except ApiError as exc:
                            self.logger.error(
                                "Błąd pobierania etykiety %s/%s: %s",
                                courier_code,
                                package_id,
                                exc,
                            )
                            PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
                            continue
                        if label_data:
                            labels.append((label_data, ext))

                    if courier_code:
                        self.last_order_data["courier_code"] = courier_code

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
                            self.send_messenger_message(self.last_order_data)
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
                                self.send_messenger_message(self.last_order_data)
                                self.mark_as_printed(order_id, self.last_order_data)
                                printed[order_id] = datetime.now()
                                for entry in entries:
                                    if entry in queue:
                                        queue.remove(entry)
                            except Exception as exc:
                                self.logger.error(
                                    "Błąd drukowania zamówienia %s: %s", order_id, exc
                                )
                                for entry in entries:
                                    entry["status"] = "queued"
                                self.save_queue(queue)
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
                fcntl.flock(self._lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
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

    def stop_agent_thread(self) -> None:
        if self._agent_thread and self._agent_thread.is_alive():
            self._stop_event.set()
            self._agent_thread.join()
            self._agent_thread = None
        self._clear_heartbeat()
        if self._lock_handle:
            try:
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
