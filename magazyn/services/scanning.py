"""Logika biznesowa dla skanowania etykiet i kodów."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import text

from ..db import db_connect, get_session
from ..models import PrintedOrder


logger = logging.getLogger(__name__)


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


def barcode_matches_order(order_data: dict[str, Any], barcode: str) -> bool:
    """Sprawdź, czy kod z etykiety pasuje do zapisanych danych zamówienia."""
    package_ids = order_data.get("package_ids") or []
    tracking_numbers = order_data.get("tracking_numbers") or []
    delivery_package_nr = str(order_data.get("delivery_package_nr") or "").strip()

    if barcode in package_ids or barcode in tracking_numbers:
        return True
    if delivery_package_nr and barcode == delivery_package_nr:
        return True

    for tracking_number in tracking_numbers:
        tracking_number = str(tracking_number or "")
        if len(tracking_number) >= 6 and tracking_number in barcode:
            return True
        if len(barcode) >= 6 and barcode in tracking_number:
            return True

    if delivery_package_nr and len(delivery_package_nr) >= 6:
        return delivery_package_nr in barcode or barcode in delivery_package_nr

    return False


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


__all__ = ["barcode_matches_order", "load_order_for_barcode", "parse_last_order_data"]