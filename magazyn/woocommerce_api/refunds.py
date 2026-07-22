"""WooCommerce order refunds (REST)."""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from .client import WooClient, WooClientError

logger = logging.getLogger(__name__)

TWOPLACES = Decimal("0.01")


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except Exception:
        return default


def list_order_refunds(
    woo_order_id: str | int,
    *,
    client: Optional[WooClient] = None,
) -> list[dict]:
    woo_id = str(woo_order_id).removeprefix("woo_").strip()
    woo = client or WooClient()
    payload = woo.get(f"wp-json/wc/v3/orders/{woo_id}/refunds")
    return payload if isinstance(payload, list) else []


def create_order_refund(
    woo_order_id: str | int,
    *,
    amount: Decimal | float | str,
    reason: Optional[str] = None,
    line_items: Optional[list[dict]] = None,
    api_refund: bool = True,
    client: Optional[WooClient] = None,
) -> dict[str, Any]:
    """Utworz zwrot w Woo (WooPayments zwykle zwraca srodki kupujacemu).

    Returns:
        dict with success, refund_id, amount, raw, error
    """
    woo_id = str(woo_order_id).removeprefix("woo_").strip()
    amount_dec = _to_decimal(amount)
    result: dict[str, Any] = {
        "success": False,
        "refund_id": None,
        "amount": amount_dec,
        "raw": None,
        "error": None,
    }
    if amount_dec <= 0:
        result["error"] = "Kwota zwrotu musi byc > 0"
        return result

    body: dict[str, Any] = {
        "amount": str(amount_dec),
        "reason": reason or "Zwrot z magazynu Retriever Shop",
        "api_refund": bool(api_refund),
    }
    if line_items:
        body["line_items"] = line_items

    try:
        woo = client or WooClient()
        raw = woo.post(f"wp-json/wc/v3/orders/{woo_id}/refunds", json=body)
        result["raw"] = raw
        result["refund_id"] = (raw or {}).get("id")
        result["success"] = bool(result["refund_id"])
        if not result["success"]:
            result["error"] = f"Woo nie zwrocil id refundu: {raw}"
        return result
    except WooClientError as exc:
        logger.error("Woo refund order=%s failed: %s", woo_id, exc)
        result["error"] = str(exc)
        return result
    except Exception as exc:
        logger.exception("Woo refund order=%s unexpected error", woo_id)
        result["error"] = str(exc)
        return result


__all__ = ["create_order_refund", "list_order_refunds"]
