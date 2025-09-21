from __future__ import annotations

import base64
import fcntl
import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, time as dt_time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from magazyn import DB_PATH

from .config import load_config, settings
from .db import sqlite_connect
from .notifications import send_report
from .parsing import parse_product_info
from .services import consume_order_stock, get_sales_summary


class ConfigError(Exception):
    """Raised when required configuration is missing."""


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
        )

    def with_updates(self, **kwargs: Any) -> "AgentConfig":
        return replace(self, **kwargs)


class LabelAgent:
    """Encapsulates the state and behaviour of the label printing agent."""

    def __init__(self, config: AgentConfig, settings_obj: Any):
        self.config = config
        self.settings = settings_obj
        self.logger = logging.getLogger(__name__)
        self.last_order_data: Dict[str, Any] = {}
        self._agent_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock_handle = None
        self._api_calls_total = 0
        self._api_calls_success = 0
        self._last_api_log = datetime.now()
        self._headers = {
            "X-BLToken": config.api_token,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        self._configure_logging(initial=True)
        self._configure_db_engine()

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
            "order_id TEXT, label_data TEXT, ext TEXT, last_order_data TEXT)"
        )
        conn.commit()

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
        conn.close()

    def clean_old_printed_orders(self) -> None:
        threshold = datetime.now() - timedelta(days=self.config.printed_expiry_days)
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM printed_orders WHERE printed_at < ?",
            (threshold.isoformat(),),
        )
        conn.commit()
        conn.close()

    def load_queue(self) -> List[Dict[str, Any]]:
        self.ensure_db()
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        cur.execute(
            "SELECT order_id, label_data, ext, last_order_data FROM label_queue"
        )
        rows = cur.fetchall()
        conn.close()
        items: List[Dict[str, Any]] = []
        for order_id, label_data, ext, last_order_json in rows:
            try:
                last_data = json.loads(last_order_json) if last_order_json else {}
            except Exception:  # pragma: no cover - defensive
                last_data = {}
            items.append(
                {
                    "order_id": order_id,
                    "label_data": label_data,
                    "ext": ext,
                    "last_order_data": last_data,
                }
            )
        return items

    def save_queue(self, items: Iterable[Dict[str, Any]]) -> None:
        conn = sqlite_connect(self.config.db_file)
        cur = conn.cursor()
        cur.execute("DELETE FROM label_queue")
        for item in items:
            cur.execute(
                "INSERT INTO label_queue(order_id, label_data, ext, last_order_data) VALUES (?, ?, ?, ?)",
                (
                    item.get("order_id"),
                    item.get("label_data"),
                    item.get("ext"),
                    json.dumps(item.get("last_order_data", {})),
                ),
            )
        conn.commit()
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

    def call_api(self, method: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        parameters = parameters or {}
        success = False
        try:
            payload = {"method": method, "parameters": json.dumps(parameters)}
            response = requests.post(
                self.config.base_url, headers=self._headers, data=payload, timeout=10
            )
            response.raise_for_status()
            success = True
            return response.json()
        except requests.exceptions.HTTPError as exc:
            self.logger.error("HTTP error in call_api(%s): %s", method, exc)
        except requests.exceptions.RequestException as exc:
            self.logger.error("Request error in call_api(%s): %s", method, exc)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Błąd w call_api(%s): %s", method, exc)
        finally:
            self._api_calls_total += 1
            if success:
                self._api_calls_success += 1
            self._maybe_log_api_summary()
        return {}

    def get_orders(self) -> List[Dict[str, Any]]:
        response = self.call_api(
            "getOrders", {"status_id": self.config.status_id, "include_products": 1}
        )
        return response.get("orders", [])

    def get_order_packages(self, order_id: str) -> List[Dict[str, Any]]:
        response = self.call_api("getOrderPackages", {"order_id": order_id})
        return response.get("packages", [])

    def get_label(self, courier_code: str, package_id: str) -> Tuple[str, str]:
        response = self.call_api(
            "getLabel", {"courier_code": courier_code, "package_id": package_id}
        )
        return response.get("label"), response.get("extension", "pdf")

    def print_label(self, base64_data: str, extension: str, order_id: str) -> None:
        try:
            file_path = f"/tmp/label_{order_id}.{extension}"
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
            os.remove(file_path)
            if result.returncode != 0:
                self.logger.error(
                    "Błąd drukowania (kod %s): %s",
                    result.returncode,
                    result.stderr.decode().strip(),
                )
            else:
                self.logger.info("📨 Label printed")
        except Exception as exc:
            self.logger.error("Błąd drukowania: %s", exc)

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
                    f"- {shorten_product_name(p['name'])} (x{p['quantity']})\n"
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
                    self.print_label(it["label_data"], it.get("ext", "pdf"), it["order_id"])
                consume_order_stock(items[0].get("last_order_data", {}).get("products", []))
                self.mark_as_printed(oid, items[0].get("last_order_data"))
                printed[oid] = datetime.now()
            except Exception as exc:
                self.logger.error("Błąd przetwarzania z kolejki: %s", exc)
                new_queue.extend(items)
        return new_queue

    def _agent_loop(self) -> None:
        while not self._stop_event.is_set():
            self._send_periodic_reports()
            self.clean_old_printed_orders()
            printed_entries = self.load_printed_orders()
            printed = {entry["order_id"]: entry["printed_at"] for entry in printed_entries}
            queue = self.load_queue()

            queue = self._process_queue(queue, printed)
            self.save_queue(queue)

            try:
                orders = self.get_orders()
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

                    packages = self.get_order_packages(order_id)
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
                        label_data, ext = self.get_label(courier_code, package_id)
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
                                    }
                                )
                            self.send_messenger_message(self.last_order_data)
                            self.mark_as_printed(order_id, self.last_order_data)
                            printed[order_id] = datetime.now()
                        else:
                            for label_data, ext in labels:
                                self.print_label(label_data, ext, order_id)
                            consume_order_stock(self.last_order_data.get("products", []))
                            self.send_messenger_message(self.last_order_data)
                            self.mark_as_printed(order_id, self.last_order_data)
                            printed[order_id] = datetime.now()
            except Exception as exc:
                self.logger.error("[BŁĄD GŁÓWNY] %s", exc)

            self.save_queue(queue)
            self._stop_event.wait(self.config.poll_interval)

    def start_agent_thread(self) -> bool:
        if self._agent_thread and self._agent_thread.is_alive():
            return False
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
        self._stop_event = threading.Event()
        self._agent_thread = threading.Thread(target=self._agent_loop, daemon=True)
        self._agent_thread.start()
        return True

    def stop_agent_thread(self) -> None:
        if self._agent_thread and self._agent_thread.is_alive():
            self._stop_event.set()
            self._agent_thread.join()
            self._agent_thread = None
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
    "agent",
    "logger",
    "parse_time_str",
    "shorten_product_name",
]
