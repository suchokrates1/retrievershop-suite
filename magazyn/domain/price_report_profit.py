"""Kalkulacje zysku dla raportów cenowych."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ..models.allegro import AllegroOffer
from ..models.price_reports import PriceReportItem
from ..models.products import ProductSize, PurchaseBatch, ShippingThreshold


ALLEGRO_FEE_PERCENT = Decimal("0.123")
ALLEGRO_FIXED_FEE = Decimal("1.0")
DEFAULT_SHIPPING_COST = Decimal("8.99")
DEFAULT_PACKAGING_COST = Decimal("0.16")


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None:
            return default
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _round_float(value: Decimal) -> float:
    return round(float(value), 2)


def _average_purchase_price(session, product_size: ProductSize) -> Decimal:
    batches = session.query(PurchaseBatch).filter(
        PurchaseBatch.product_id == product_size.product_id,
        PurchaseBatch.size == product_size.size,
    ).all()
    if not batches:
        return Decimal("0")

    total_qty = sum(int(batch.quantity or 0) for batch in batches)
    if total_qty <= 0:
        return Decimal("0")

    total_value = sum(
        Decimal(int(batch.quantity or 0)) * _to_decimal(batch.price)
        for batch in batches
    )
    return total_value / Decimal(total_qty)


def _shipping_cost_for_price(session, our_price: Decimal) -> Decimal:
    thresholds = session.query(ShippingThreshold).order_by(
        ShippingThreshold.min_order_value.desc()
    ).all()
    for threshold in thresholds:
        if our_price >= _to_decimal(threshold.min_order_value):
            return _to_decimal(threshold.shipping_cost, DEFAULT_SHIPPING_COST)
    return DEFAULT_SHIPPING_COST


def build_profit_data(
    *,
    our_price: Decimal,
    competitor_price: Decimal,
    purchase_price: Optional[Decimal],
    shipping_cost: Decimal,
    packaging_cost: Decimal,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Zbuduj payload kalkulacji zysku używany przez API raportów cenowych."""
    target_price = competitor_price - Decimal("0.01") if competitor_price > 0 else our_price
    price_change_percent = (
        (our_price - target_price) / our_price * Decimal("100")
        if our_price > 0
        else Decimal("0")
    )
    purchase = purchase_price if purchase_price is not None else Decimal("0")

    def calc(price: Decimal) -> Decimal:
        allegro_fees = price * ALLEGRO_FEE_PERCENT + ALLEGRO_FIXED_FEE
        return price - purchase - allegro_fees - shipping_cost - packaging_cost

    current_profit = calc(our_price)
    new_profit = calc(target_price)
    data = {
        "current_price": float(our_price),
        "target_price": _round_float(target_price),
        "price_change_percent": _round_float(price_change_percent),
        "current_profit": _round_float(current_profit),
        "new_profit": _round_float(new_profit),
        "profit_change": _round_float(new_profit - current_profit),
        "purchase_price": float(purchase_price) if purchase_price is not None else None,
        "competitor_price": float(competitor_price),
    }
    if note:
        data["note"] = note
    return data


def build_fallback_profit_data(
    our_price: Decimal,
    competitor_price: Decimal,
    packaging_cost: Decimal = DEFAULT_PACKAGING_COST,
) -> dict[str, Any]:
    return build_profit_data(
        our_price=our_price,
        competitor_price=competitor_price,
        purchase_price=None,
        shipping_cost=DEFAULT_SHIPPING_COST,
        packaging_cost=packaging_cost,
        note="Brak danych o cenie zakupu - pokazano zysk bez kosztu towaru",
    )


def calculate_report_item_profit(
    session,
    item: PriceReportItem,
    *,
    packaging_cost: Any = DEFAULT_PACKAGING_COST,
) -> dict[str, Any]:
    """Oblicz dane zysku dla pozycji raportu cenowego."""
    our_price = _to_decimal(item.our_price)
    competitor_price = _to_decimal(item.competitor_price)
    packaging = _to_decimal(packaging_cost, DEFAULT_PACKAGING_COST)

    offer = session.query(AllegroOffer).filter(
        AllegroOffer.offer_id == item.offer_id,
    ).first()
    if not offer or not offer.product_size_id:
        return build_fallback_profit_data(our_price, competitor_price, packaging)

    product_size = session.query(ProductSize).filter(
        ProductSize.id == offer.product_size_id,
    ).first()
    if not product_size:
        return build_fallback_profit_data(our_price, competitor_price, packaging)

    purchase_price = _average_purchase_price(session, product_size)
    shipping_cost = _shipping_cost_for_price(session, our_price)
    return build_profit_data(
        our_price=our_price,
        competitor_price=competitor_price,
        purchase_price=purchase_price,
        shipping_cost=shipping_cost,
        packaging_cost=packaging,
    )


__all__ = [
    "build_fallback_profit_data",
    "build_profit_data",
    "calculate_report_item_profit",
]