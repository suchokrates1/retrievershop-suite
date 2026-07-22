"""Synchronizacja zamowien WooCommerce → magazyn."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc

from ..db import get_session
from ..models.orders import Order, OrderStatusLog
from ..notifications.alerts import send_critical_alert
from ..woocommerce_api import WooClient, WooClientError
from ..woocommerce_api.orders import fetch_order, fetch_orders, parse_woo_order_to_data
from .order_status import add_order_status
from .order_sync import sync_order_from_data
from ..settings_store import settings_store

logger = logging.getLogger(__name__)


def verify_woo_webhook_signature(body: bytes, signature: str) -> bool:
    secret = settings_store.get("WOO_WEBHOOK_SECRET") or ""
    if not secret:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    import base64

    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature or "")


def import_woo_order(order_payload: dict) -> dict[str, Any]:
    """Zaimportuj jedno zamowienie Woo (dict z API)."""
    order_data = parse_woo_order_to_data(order_payload)
    woo_status = order_data.pop("woo_status", None)

    # Tylko oplacone / do realizacji
    if woo_status in {"pending", "failed", "cancelled", "refunded", "checkout-draft"}:
        return {"skipped": True, "reason": f"status={woo_status}", "order_id": order_data["order_id"]}

    with get_session() as db:
        existing = db.query(Order).filter(Order.order_id == order_data["order_id"]).first()
        if existing:
            latest = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == existing.order_id)
                .order_by(desc(OrderStatusLog.timestamp))
                .first()
            )
            # Nie wskrzeszaj zamowien anulowanych w magazynie (stare processing z Woo)
            if latest and latest.status == "anulowano":
                return {
                    "skipped": True,
                    "reason": "anulowano_w_magazynie",
                    "order_id": order_data["order_id"],
                }

        is_new = existing is None
        sync_order_from_data(db, order_data)

        if is_new:
            add_order_status(
                db,
                order_data["order_id"],
                "pobrano",
                notes=f"Import z WooCommerce #{order_data.get('shop_order_id')}",
                send_email=True,
            )
            db.commit()
            try:
                send_critical_alert(
                    f"Nowe zamowienie Woo #{order_data.get('shop_order_id')}",
                    f"{order_data.get('customer')} — {order_data.get('payment_done')} PLN\n"
                    f"{order_data['order_id']}",
                )
            except Exception:
                logger.exception("Nie wyslano alertu o Woo order")
        else:
            db.commit()

        # Cache realnego zysku (WooPayments + InPost) — best effort
        try:
            from ..domain.financial import FinancialCalculator

            order_row = db.query(Order).filter(Order.order_id == order_data["order_id"]).first()
            if order_row is not None:
                FinancialCalculator(db, settings_store).refresh_order_profit_cache(
                    order_row,
                    trace_label="woo-import",
                )
                db.commit()
        except Exception:
            logger.exception("Nie odswiezono zysku Woo dla %s", order_data["order_id"])

    return {"skipped": False, "order_id": order_data["order_id"], "is_new": is_new}


def sync_woo_orders(*, days: int = 14) -> dict[str, int]:
    """Poll Woo API i zaimportuj zamowienia processing/completed z ostatnich N dni."""
    stats = {"fetched": 0, "imported": 0, "skipped": 0, "errors": 0}
    try:
        client = WooClient()
    except WooClientError as exc:
        logger.error("Woo order sync: %s", exc)
        return {**stats, "errors": 1}

    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        orders = fetch_orders(
            client,
            status="processing,completed",
            after=after,
            per_page=50,
        )
    except Exception:
        logger.exception("Blad pobierania zamowien Woo")
        return {**stats, "errors": 1}

    stats["fetched"] = len(orders)
    for order in orders:
        try:
            result = import_woo_order(order)
            if result.get("skipped"):
                stats["skipped"] += 1
            else:
                stats["imported"] += 1
        except Exception:
            logger.exception("Blad importu Woo order %s", order.get("id"))
            stats["errors"] += 1
    return stats


def import_woo_order_by_id(woo_order_id: int | str) -> dict[str, Any]:
    client = WooClient()
    order = fetch_order(client, woo_order_id)
    return import_woo_order(order)


__all__ = [
    "import_woo_order",
    "import_woo_order_by_id",
    "sync_woo_orders",
    "verify_woo_webhook_signature",
]
