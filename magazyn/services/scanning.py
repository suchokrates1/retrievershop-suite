"""Logika biznesowa dla skanowania etykiet i kodów."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, MutableMapping, Optional

from sqlalchemy import desc, text

from ..db import db_connect, get_session
from ..models.orders import OrderProduct, OrderStatusLog
from ..models.printing import PrintedOrder, ScanLog
from ..services.order_status import add_order_status


logger = logging.getLogger(__name__)

AUTO_PACK_SCAN_TTL_SECONDS = 120
AUTO_PACK_REQUIRED_STATUS = "wydrukowano"
AUTO_PACK_TARGET_STATUS = "spakowano"


@dataclass(frozen=True)
class AutoPackResult:
    """Wynik próby automatycznego spakowania zamówienia."""

    status: str
    order_id: str | None = None
    flash_message: str | None = None
    flash_category: str | None = None
    state_modified: bool = False


def parse_last_order_data(raw: Any) -> dict[str, Any]:
    """Zwróć dane zamówienia niezależnie od formatu zapisu."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def barcode_scan_candidates(barcode: str) -> list[str]:
    """Rozszerz kod skanera o warianty używane na etykietach przewoźników."""
    barcode = barcode.strip()
    if not barcode:
        return []

    candidates = [barcode]
    if "+" in barcode:
        upper = barcode.upper()
        if upper.startswith("2L"):
            # Routing DHL/Orlen: unikalny jest prefiks przed '+', sufiks bywa wspólny.
            prefix = barcode.split("+", 1)[0].strip()
            if prefix:
                candidates.append(prefix)
        else:
            for part in barcode.split("+"):
                part = part.strip()
                if part:
                    candidates.append(part)

    if barcode.upper().startswith("JJD"):
        digits = re.sub(r"\D", "", barcode)
        if digits:
            candidates.append(digits)
            if len(digits) >= 11:
                candidates.append(digits[-11:])

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def barcode_matches_order(order_data: dict[str, Any], barcode: str) -> bool:
    """Sprawdź, czy kod z etykiety pasuje do zapisanych danych zamówienia."""
    package_ids = order_data.get("package_ids") or []
    tracking_numbers = [str(value) for value in (order_data.get("tracking_numbers") or [])]
    delivery_package_nr = str(order_data.get("delivery_package_nr") or "").strip()

    for candidate in barcode_scan_candidates(barcode):
        if candidate in package_ids or candidate in tracking_numbers:
            return True
        if delivery_package_nr and candidate == delivery_package_nr:
            return True

        for tracking_number in tracking_numbers:
            tracking_number = str(tracking_number or "")
            if len(tracking_number) >= 6 and tracking_number in candidate:
                return True
            if len(candidate) >= 6 and candidate in tracking_number:
                return True

        if delivery_package_nr and len(delivery_package_nr) >= 6:
            if delivery_package_nr in candidate or candidate in delivery_package_nr:
                return True

    return False


def record_scan_event(
    scan_type: str,
    barcode: str,
    success: bool,
    *,
    result_data: Any = None,
    error_message: str | None = None,
    user_id: int | None = None,
    log: logging.Logger | None = None,
) -> None:
    """Zapisz zdarzenie skanu do bazy na potrzeby audytu i diagnostyki."""
    try:
        with get_session() as db_session:
            db_session.add(
                ScanLog(
                    scan_type=scan_type,
                    barcode=barcode,
                    success=success,
                    result_data=json.dumps(result_data) if result_data else None,
                    error_message=error_message,
                    user_id=user_id,
                )
            )
    except Exception as exc:
        target_log = log or logger
        target_log.warning("Nie udało się zapisać logu skanu: %s", exc)


def check_and_auto_pack(
    scan_state: MutableMapping[str, Any],
    *,
    now: float | None = None,
    max_scan_age_seconds: int = AUTO_PACK_SCAN_TTL_SECONDS,
    log: logging.Logger | None = None,
) -> AutoPackResult:
    """Sprawdź, czy ostatni skan produktu i etykiety pozwalają spakować zamówienie."""
    target_log = log or logger
    last_product = scan_state.get("last_product_scan") or {}
    last_label = scan_state.get("last_label_scan") or {}

    if not last_product or not last_label:
        target_log.info(
            "Auto-pack check: product=%s, label=%s",
            bool(last_product),
            bool(last_label),
        )
        return AutoPackResult(status="waiting")

    current_timestamp = time.time() if now is None else now
    product_age = _scan_age_seconds(last_product, current_timestamp)
    label_age = _scan_age_seconds(last_label, current_timestamp)
    target_log.info(
        "Auto-pack check: product_age=%.1fs, label_age=%.1fs",
        product_age,
        label_age,
    )

    if product_age > max_scan_age_seconds or label_age > max_scan_age_seconds:
        target_log.info("Auto-pack: Timeout - skany za stare")
        _clear_auto_pack_state(scan_state)
        return AutoPackResult(status="expired", state_modified=True)

    order_id = str(last_label.get("order_id") or "").strip()
    product_size_id = _to_positive_int(last_product.get("product_size_id"))
    if not order_id or product_size_id is None:
        return AutoPackResult(status="invalid_scan")

    with get_session() as db_session:
        latest_status = (
            db_session.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order_id)
            .order_by(desc(OrderStatusLog.timestamp))
            .first()
        )
        current_status = latest_status.status if latest_status else "nieznany"
        target_log.info("Auto-pack: order_id=%s, current_status=%s", order_id, current_status)

        if not latest_status or latest_status.status != AUTO_PACK_REQUIRED_STATUS:
            target_log.info("Auto-pack: Status nie jest '%s' - pomijam", AUTO_PACK_REQUIRED_STATUS)
            return AutoPackResult(status="wrong_status", order_id=order_id)

        order_products = (
            db_session.query(OrderProduct)
            .filter(OrderProduct.order_id == order_id)
            .all()
        )
        required_counts = _required_product_counts(order_products)
        if not required_counts:
            target_log.warning("Auto-pack: Brak produktów z product_size_id dla zamówienia %s", order_id)
            return AutoPackResult(status="no_required_products", order_id=order_id)

        if product_size_id not in required_counts:
            target_log.warning(
                "Auto-pack: Produkt %s NIE należy do zamówienia %s",
                product_size_id,
                order_id,
            )
            return AutoPackResult(
                status="product_mismatch",
                order_id=order_id,
                flash_message="Zeskanowany produkt nie należy do tej paczki!",
                flash_category="warning",
            )

        tracked_orders = scan_state.get("scanned_products_for_order") or {}
        order_key = str(order_id)
        scanned_counts, scan_keys = _normalize_order_tracking(tracked_orders.get(order_key))
        scan_key = _product_scan_key(last_product)
        state_modified = False
        if scan_key not in scan_keys:
            scanned_counts[product_size_id] += 1
            scan_keys.add(scan_key)
            state_modified = True

        tracked_orders[order_key] = _serialize_order_tracking(scanned_counts, scan_keys)
        scan_state["scanned_products_for_order"] = tracked_orders

        scanned_total = _matched_scan_total(required_counts, scanned_counts)
        required_total = sum(required_counts.values())
        missing_total = required_total - scanned_total
        if missing_total > 0:
            target_log.info(
                "Auto-pack: Zeskanowano %s/%s produktów dla zamówienia %s",
                scanned_total,
                required_total,
                order_id,
            )
            return AutoPackResult(
                status="partial",
                order_id=order_id,
                flash_message=f"Zeskanowano {scanned_total}/{required_total} produktów",
                flash_category="info",
                state_modified=state_modified,
            )

        add_order_status(
            db_session,
            order_id,
            AUTO_PACK_TARGET_STATUS,
            notes="Automatycznie spakowano po zeskanowaniu etykiety i produktów",
        )
        target_log.info("AUTO-PACK SUCCESS: Zamówienie %s -> %s", order_id, AUTO_PACK_TARGET_STATUS)

        _clear_auto_pack_state(scan_state, order_key=order_key)
        return AutoPackResult(
            status="packed",
            order_id=order_id,
            flash_message=f"Spakowano zamówienie {order_id}!",
            flash_category="success",
            state_modified=True,
        )


def load_order_for_barcode(barcode: str) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """Wczytaj zamówienie dla kodu etykiety lub numeru śledzenia."""
    barcode = barcode.strip()
    matched_order_id = None
    order_data = None

    with get_session() as db_session:
        direct = db_session.get(PrintedOrder, barcode)
        if direct:
            matched_order_id = direct.order_id
            order_data = parse_last_order_data(direct.last_order_data)

        if not order_data:
            for printed_order in db_session.query(PrintedOrder).all():
                data = parse_last_order_data(printed_order.last_order_data)
                if barcode_matches_order(data, barcode):
                    matched_order_id = printed_order.order_id
                    order_data = data
                    break

    if order_data:
        return matched_order_id, order_data

    try:
        with db_connect() as conn:
            rows = conn.execute(
                text("SELECT order_id, last_order_data FROM label_queue")
            ).fetchall()
            for order_id, data_json in rows:
                data = parse_last_order_data(data_json)
                if barcode == order_id or barcode_matches_order(data, barcode):
                    return order_id, data
    except Exception as exc:
        logger.debug("Nie udało się sprawdzić kolejki etykiet dla kodu %s: %s", barcode, exc)

    return None, None


def _scan_age_seconds(scan_data: dict[str, Any], current_timestamp: float) -> float:
    try:
        return current_timestamp - float(scan_data.get("timestamp") or 0)
    except (TypeError, ValueError):
        return float("inf")


def _to_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clear_auto_pack_state(scan_state: MutableMapping[str, Any], *, order_key: str | None = None) -> None:
    scan_state.pop("last_product_scan", None)
    scan_state.pop("last_label_scan", None)
    if order_key is None:
        scan_state.pop("scanned_products_for_order", None)
        return

    tracked_orders = scan_state.get("scanned_products_for_order") or {}
    tracked_orders.pop(order_key, None)
    if tracked_orders:
        scan_state["scanned_products_for_order"] = tracked_orders
    else:
        scan_state.pop("scanned_products_for_order", None)


def _required_product_counts(order_products: list[OrderProduct]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for order_product in order_products:
        product_size_id = _to_positive_int(order_product.product_size_id)
        if product_size_id is None:
            continue
        quantity = _to_positive_int(order_product.quantity) or 1
        counts[product_size_id] += quantity
    return counts


def _normalize_order_tracking(raw_tracking: Any) -> tuple[Counter[int], set[str]]:
    counts: Counter[int] = Counter()
    scan_keys: set[str] = set()

    if isinstance(raw_tracking, dict) and isinstance(raw_tracking.get("counts"), dict):
        for raw_product_size_id, raw_count in raw_tracking["counts"].items():
            product_size_id = _to_positive_int(raw_product_size_id)
            count = _to_positive_int(raw_count)
            if product_size_id is not None and count is not None:
                counts[product_size_id] += count
        scan_keys = {str(scan_key) for scan_key in raw_tracking.get("scan_keys", []) if scan_key}
        return counts, scan_keys

    if isinstance(raw_tracking, list):
        for raw_product_size_id in raw_tracking:
            product_size_id = _to_positive_int(raw_product_size_id)
            if product_size_id is not None:
                counts[product_size_id] += 1

    return counts, scan_keys


def _serialize_order_tracking(scanned_counts: Counter[int], scan_keys: set[str]) -> dict[str, Any]:
    return {
        "counts": {
            str(product_size_id): count
            for product_size_id, count in scanned_counts.items()
            if count > 0
        },
        "scan_keys": sorted(scan_keys),
    }


def _product_scan_key(last_product: dict[str, Any]) -> str:
    explicit_key = last_product.get("scan_key")
    if explicit_key:
        return str(explicit_key)
    return ":".join(
        str(last_product.get(part) or "")
        for part in ("barcode", "product_size_id", "timestamp")
    )


def _matched_scan_total(required_counts: Counter[int], scanned_counts: Counter[int]) -> int:
    return sum(
        min(scanned_counts.get(product_size_id, 0), required_count)
        for product_size_id, required_count in required_counts.items()
    )


__all__ = [
    "AUTO_PACK_REQUIRED_STATUS",
    "AUTO_PACK_SCAN_TTL_SECONDS",
    "AUTO_PACK_TARGET_STATUS",
    "AutoPackResult",
    "barcode_matches_order",
    "barcode_scan_candidates",
    "check_and_auto_pack",
    "load_order_for_barcode",
    "parse_last_order_data",
    "record_scan_event",
]
