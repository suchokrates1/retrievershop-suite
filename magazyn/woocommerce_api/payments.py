"""WooPayments — opłaty transakcyjne (Transactions Reporting API)."""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from ..settings_store import settings_store
from .client import WooClient, WooClientError

logger = logging.getLogger(__name__)

TWOPLACES = Decimal("0.01")

# Domyslne stawki WooPayments PL (docs WooCommerce)
DEFAULT_CARD_PCT = Decimal("1.50")
DEFAULT_CARD_FIXED = Decimal("1.00")
DEFAULT_P24_PCT = Decimal("1.90")
DEFAULT_P24_FIXED = Decimal("1.00")


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _settings_decimal(key: str, default: Decimal) -> Decimal:
    raw = settings_store.get(key)
    if raw is None or raw == "":
        return default
    return _to_decimal(raw, default)


def classify_woo_payment_method(payment_method: Optional[str]) -> str:
    """Zwraca: cod | p24 | card | other."""
    text = (payment_method or "").strip().lower()
    if not text:
        return "other"
    if text in {"cod", "pobranie"} or "pobranie" in text or "cash on delivery" in text:
        return "cod"
    if (
        "p24" in text
        or "przelewy" in text
        or text in {"przelewy24", "woocommerce_payments_przelewy24"}
    ):
        return "p24"
    if any(
        token in text
        for token in (
            "card",
            "visa",
            "mastercard",
            "apple",
            "google",
            "woocommerce_payments",
            "stripe",
            "link",
            "woopay",
        )
    ):
        return "card"
    return "other"


def estimate_woo_payment_fee(
    sale_price: Decimal,
    payment_method: Optional[str] = None,
) -> Decimal:
    """Szacunek opłaty WooPayments z ustawień (fallback gdy brak API)."""
    kind = classify_woo_payment_method(payment_method)
    if kind == "cod":
        return Decimal("0.00")

    if kind == "p24":
        pct = _settings_decimal("WOO_FEE_P24_PCT", DEFAULT_P24_PCT)
        fixed = _settings_decimal("WOO_FEE_P24_FIXED", DEFAULT_P24_FIXED)
    else:
        # card / other — traktuj jak kartę (dominująca metoda)
        pct = _settings_decimal("WOO_FEE_CARD_PCT", DEFAULT_CARD_PCT)
        fixed = _settings_decimal("WOO_FEE_CARD_FIXED", DEFAULT_CARD_FIXED)

    fee = (sale_price * pct / Decimal("100")) + fixed
    return fee.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _minor_units_to_pln(value: Any) -> Decimal:
    """WooPayments raportuje kwoty w najmniejszych jednostkach (grosze)."""
    amount = _to_decimal(value)
    # Heurystyka: wartości całkowite >= 1 traktujemy jako grosze;
    # ułamki już w PLN (na wypadek zmiany API).
    if amount == amount.to_integral_value() and abs(amount) >= 1:
        return (amount / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _sum_charge_fees(transactions: list[dict]) -> tuple[Decimal, Optional[str]]:
    total = Decimal("0.00")
    method = None
    for txn in transactions:
        txn_type = (txn.get("type") or "").lower()
        if txn_type and txn_type not in {"charge", "payment"}:
            continue
        fees = txn.get("fees")
        if fees is None:
            continue
        total += _minor_units_to_pln(fees)
        pm = txn.get("payment_method") or {}
        if isinstance(pm, dict) and pm.get("type"):
            method = str(pm["type"])
        elif isinstance(pm, str):
            method = pm
    return total.quantize(TWOPLACES, rounding=ROUND_HALF_UP), method


def get_order_payment_fees(
    woo_order_id: str | int,
    *,
    sale_price: Optional[Decimal] = None,
    payment_method: Optional[str] = None,
    client: Optional[WooClient] = None,
) -> dict[str, Any]:
    """Pobierz opłaty WooPayments dla zamówienia WC.

    Returns:
        dict: fees, fee_source ('api'|'estimated'), payment_method, amount,
              net_amount, transactions, error, success
    """
    woo_id = str(woo_order_id).removeprefix("woo_").strip()
    kind = classify_woo_payment_method(payment_method)
    if kind == "cod":
        return {
            "success": True,
            "fees": Decimal("0.00"),
            "fee_source": "api",
            "payment_method": payment_method or "cod",
            "amount": None,
            "net_amount": None,
            "transactions": [],
            "error": None,
        }

    result: dict[str, Any] = {
        "success": False,
        "fees": Decimal("0.00"),
        "fee_source": "estimated",
        "payment_method": payment_method,
        "amount": None,
        "net_amount": None,
        "transactions": [],
        "error": None,
    }

    try:
        woo = client or WooClient()
        payload = woo.get(
            "wp-json/wc/v3/payments/reports/transactions",
            params={"order_id": woo_id, "per_page": 20, "page": 1},
        )
    except WooClientError as exc:
        logger.warning("WooPayments transactions API error for %s: %s", woo_id, exc)
        result["error"] = str(exc)
        if sale_price is not None:
            result["fees"] = estimate_woo_payment_fee(sale_price, payment_method)
            result["success"] = True
        return result
    except Exception as exc:
        logger.warning("WooPayments transactions unexpected error for %s: %s", woo_id, exc)
        result["error"] = str(exc)
        if sale_price is not None:
            result["fees"] = estimate_woo_payment_fee(sale_price, payment_method)
            result["success"] = True
        return result

    transactions: list[dict] = []
    if isinstance(payload, list):
        transactions = [t for t in payload if isinstance(t, dict)]
    elif isinstance(payload, dict):
        data = payload.get("data") or payload.get("transactions") or []
        if isinstance(data, list):
            transactions = [t for t in data if isinstance(t, dict)]

    result["transactions"] = transactions
    if not transactions:
        result["error"] = "no_transactions"
        if sale_price is not None:
            result["fees"] = estimate_woo_payment_fee(sale_price, payment_method)
            result["success"] = True
        return result

    fees, api_method = _sum_charge_fees(transactions)
    if api_method:
        result["payment_method"] = api_method

    first = transactions[0]
    if first.get("amount") is not None:
        result["amount"] = _minor_units_to_pln(first["amount"])
    if first.get("net_amount") is not None:
        result["net_amount"] = _minor_units_to_pln(first["net_amount"])

    result["fees"] = fees
    result["fee_source"] = "api"
    result["success"] = True
    return result


__all__ = [
    "classify_woo_payment_method",
    "estimate_woo_payment_fee",
    "get_order_payment_fees",
]
