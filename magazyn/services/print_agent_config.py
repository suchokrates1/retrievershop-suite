"""Konfiguracja i czyste helpery agenta drukowania."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, replace
from datetime import time as dt_time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from ..config import settings


class ConfigError(Exception):
    """Raised when required configuration is missing."""


def parse_time_str(value: str) -> dt_time:
    """Return time from ``HH:MM`` or raise ``ValueError``."""
    try:
        return dt_time.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid time value: {value}") from exc


def is_cod_order(payment_method_cod: Any, payment_method: Any) -> bool:
    """Return True when order should be treated as COD (pobranie)."""
    cod_value = str(payment_method_cod or "").strip().lower()
    if cod_value in {"1", "true", "t", "yes", "y"}:
        return True

    method = str(payment_method or "").strip().lower()
    method_ascii = unicodedata.normalize("NFKD", method).encode("ascii", "ignore").decode("ascii")
    return any(token in method_ascii for token in ("pobran", "cod", "cash on delivery"))


def calculate_cod_amount(order_data: dict) -> Decimal:
    """Return COD amount as sum(products) + delivery rounded to 2 decimals."""
    total = Decimal("0")
    for product in order_data.get("products", []):
        try:
            price = Decimal(str(product.get("price_brutto") or "0"))
        except (InvalidOperation, TypeError):
            price = Decimal("0")
        try:
            qty = int(product.get("quantity") or 1)
        except (ValueError, TypeError):
            qty = 1
        total += price * Decimal(qty)

    try:
        delivery_price = Decimal(str(order_data.get("delivery_price") or "0"))
    except (InvalidOperation, TypeError):
        delivery_price = Decimal("0")

    total += delivery_price
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class AgentConfig:
    page_access_token: str
    recipient_id: str
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
    base_url: str = ""
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
        base_dir = os.path.dirname(os.path.dirname(__file__))
        log_file = cfg.LOG_FILE
        lock_file = os.getenv(
            "AGENT_LOCK_FILE",
            os.path.join(os.path.dirname(log_file), "agent.lock"),
        )
        return cls(
            page_access_token=cfg.PAGE_ACCESS_TOKEN,
            recipient_id=cfg.RECIPIENT_ID,
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


__all__ = [
    "AgentConfig",
    "ConfigError",
    "calculate_cod_amount",
    "is_cod_order",
    "parse_time_str",
]