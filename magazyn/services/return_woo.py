"""Synchronizacja zwrotow Woo / WebToffee EU Withdrawal."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional

import requests

from ..db import get_session
from ..domain.returns import RETURN_STATUS_PENDING
from ..models.orders import Order
from ..models.returns import Return
from ..settings_store import settings_store
from .order_status import add_order_status
from .return_core import create_return_from_order

logger = logging.getLogger(__name__)

WOO_RETURN_CARRIER = "WOO"


def verify_woo_return_signature(body: bytes, signature: str) -> bool:
    """HMAC-SHA256 hex signature (X-Retriever-Signature)."""
    secret = (
        settings_store.get("WOO_RETURN_WEBHOOK_SECRET")
        or settings_store.get("WOO_WEBHOOK_SECRET")
        or ""
    )
    if not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = (signature or "").strip().lower()
    if provided.startswith("sha256="):
        provided = provided[7:]
    return hmac.compare_digest(expected, provided)


def _normalize_items(raw_items: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    items: List[Dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        qty = item.get("quantity") or 1
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 1
        price = item.get("price_brutto")
        if price is None:
            price = item.get("price")
        items.append(
            {
                "name": item.get("name") or "Produkt",
                "quantity": qty,
                "ean": item.get("ean"),
                "sku": item.get("sku"),
                "product_size_id": item.get("product_size_id"),
                "price_brutto": price,
                "line_item_id": item.get("line_item_id"),
                "product_id": item.get("product_id"),
                "variation_id": item.get("variation_id"),
            }
        )
    return items


def upsert_return_from_woo_withdrawal(
    payload: dict,
    *,
    log: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Utworz/aktualizuj Return z payloadu WebToffee / webhooku."""
    active_logger = log or logger
    withdrawal_id = payload.get("withdrawal_id")
    woo_order_id = payload.get("order_id")
    if not withdrawal_id or not woo_order_id:
        return {"ok": False, "error": "missing withdrawal_id or order_id"}

    magazyn_order_id = f"woo_{woo_order_id}"
    items = _normalize_items(payload.get("items"))
    reason = (payload.get("reason") or "").strip()
    notes = f"Wniosek WebToffee #{withdrawal_id}"
    if reason:
        notes = f"{notes}: {reason}"

    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == magazyn_order_id).first()
        if not order:
            # Fallback: external_order_id / shop_order_id
            order = (
                db.query(Order)
                .filter(Order.external_order_id == str(woo_order_id))
                .first()
            )
        if not order:
            active_logger.warning(
                "Woo withdrawal %s: brak zamowienia %s w magazynie",
                withdrawal_id,
                magazyn_order_id,
            )
            return {
                "ok": False,
                "error": "order_not_found",
                "order_id": magazyn_order_id,
            }

        existing = (
            db.query(Return)
            .filter(Return.woo_withdrawal_id == str(withdrawal_id))
            .first()
        )
        created = existing is None

    # create_return_from_order opens its own session
    return_record = create_return_from_order(
        order,
        return_carrier=WOO_RETURN_CARRIER,
        status=RETURN_STATUS_PENDING,
        notes=notes,
        woo_withdrawal_id=str(withdrawal_id),
        items=items or None,
        customer_name=payload.get("customer_name") or order.customer_name,
        log=active_logger,
    )
    if not return_record:
        return {"ok": False, "error": "create_failed", "order_id": order.order_id}

    with get_session() as db:
        add_order_status(
            db,
            order.order_id,
            "zwrot",
            notes=notes,
        )
        db.commit()

    active_logger.info(
        "Woo withdrawal %s -> return #%s order=%s created=%s",
        withdrawal_id,
        return_record.id,
        order.order_id,
        created,
    )
    return {
        "ok": True,
        "created": created,
        "return_id": return_record.id,
        "order_id": order.order_id,
        "woo_withdrawal_id": str(withdrawal_id),
    }


def _poll_withdrawals_from_wp(
    *,
    after_id: int = 0,
    limit: int = 50,
) -> List[dict]:
    base = (settings_store.get("WOO_URL") or "").rstrip("/")
    secret = (
        settings_store.get("WOO_RETURN_WEBHOOK_SECRET")
        or settings_store.get("WOO_WEBHOOK_SECRET")
        or ""
    )
    if not base or not secret:
        return []
    url = f"{base}/wp-json/retrievershop/v1/withdrawals"
    try:
        response = requests.get(
            url,
            params={"after_id": after_id, "limit": limit},
            headers={
                "X-Retriever-Secret": secret,
                "User-Agent": "retrievershop-magazyn/woo-returns",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            logger.warning(
                "Woo withdrawals poll HTTP %s: %s",
                response.status_code,
                response.text[:300],
            )
            return []
        data = response.json() or {}
        rows = data.get("withdrawals") or []
        return rows if isinstance(rows, list) else []
    except Exception:
        logger.exception("Woo withdrawals poll failed")
        return []


def check_woo_customer_returns(*, log: Optional[logging.Logger] = None) -> Dict[str, int]:
    """Poll backup: pobierz wnioski WebToffee i upsert Return."""
    active_logger = log or logger
    stats = {"created": 0, "existing": 0, "errors": 0, "fetched": 0}

    with get_session() as db:
        max_id_row = (
            db.query(Return.woo_withdrawal_id)
            .filter(Return.woo_withdrawal_id.isnot(None))
            .all()
        )
        after_id = 0
        for (wid,) in max_id_row:
            try:
                after_id = max(after_id, int(str(wid)))
            except (TypeError, ValueError):
                continue

    rows = _poll_withdrawals_from_wp(after_id=after_id)
    stats["fetched"] = len(rows)
    for payload in rows:
        try:
            result = upsert_return_from_woo_withdrawal(payload, log=active_logger)
            if not result.get("ok"):
                if result.get("error") == "order_not_found":
                    stats["errors"] += 1
                else:
                    stats["errors"] += 1
                continue
            if result.get("created"):
                stats["created"] += 1
            else:
                stats["existing"] += 1
        except Exception as exc:
            active_logger.error("Blad Woo withdrawal upsert: %s", exc)
            stats["errors"] += 1
    return stats


def mark_woo_return_refunded_from_order(
    order_id: str,
    *,
    log: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Reconcile: Woo status=refunded / refunds w WP → oznacz Return jako rozliczony."""
    from ..domain.returns import RETURN_STATUS_COMPLETED
    from .return_core import add_return_status_log

    active_logger = log or logger
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        if not return_record:
            return {"ok": False, "error": "no_return"}
        if return_record.refund_processed:
            return {"ok": True, "already": True}
        return_record.refund_processed = True
        return_record.status = RETURN_STATUS_COMPLETED
        add_return_status_log(
            db,
            return_record.id,
            RETURN_STATUS_COMPLETED,
            "Reconcile: zwrot pieniedzy wykryty po stronie WooCommerce",
        )
        db.commit()
        active_logger.info("Woo reconcile refund_processed order=%s", order_id)
        return {"ok": True, "return_id": return_record.id}


__all__ = [
    "WOO_RETURN_CARRIER",
    "check_woo_customer_returns",
    "mark_woo_return_refunded_from_order",
    "upsert_return_from_woo_withdrawal",
    "verify_woo_return_signature",
]
