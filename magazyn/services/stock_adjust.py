"""Reczna korekta stanu magazynowego spojna ze srednia wazona (AVCO).

Jedyne miejsce (poza record_purchase/consume_stock/zwrotami) gdzie mutujemy
``ProductSize.quantity`` - pilnuje, zeby ``stock_value`` zawsze szlo za iloscia,
inaczej srednia cena zakupu (``stock_value/quantity``) by sie rozjechala.

Reguly:
- Zwiekszenie z podana ``unit_price`` -> realny zakup, wartosc += delta*cena,
  srednia sie przesuwa.
- Zwiekszenie bez ceny -> korekta po BIEZACEJ sredniej (neutralne dla sredniej).
- Zmniejszenie -> zdejmuje proporcjonalny udzial wartosci (po sredniej); cena
  jest ignorowana, bo usuwamy istniejacy stan.
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from ..db import TWOPLACES, get_session
from ..models.products import ProductSize

logger = logging.getLogger(__name__)


def _current_avg(product_size: ProductSize) -> Decimal:
    if not product_size.quantity:
        return Decimal("0.00")
    return Decimal(str(product_size.stock_value or 0)) / Decimal(product_size.quantity)


def apply_stock_adjustment(
    product_size: ProductSize,
    *,
    set_to: Optional[int] = None,
    delta: Optional[int] = None,
    unit_price=None,
    reason: Optional[str] = None,
) -> Tuple[int, int]:
    """Rdzen korekty na juz zaladowanym ``ProductSize`` (bez otwierania sesji).

    Uzywaj tego wariantu wewnatrz istniejacej sesji (np. update_product,
    remanent), zeby nie zagniezdzac zapisow na dwoch polaczeniach SQLite.
    Semantyka jak w ``adjust_stock``.
    """
    if (set_to is None) == (delta is None):
        raise ValueError("Podaj dokladnie jedno z: set_to albo delta")

    old_qty = product_size.quantity or 0
    change = (int(set_to) - old_qty) if set_to is not None else int(delta)
    if change == 0:
        return old_qty, old_qty

    value = Decimal(str(product_size.stock_value or 0))

    if change > 0:
        if unit_price is not None:
            price = Decimal(str(unit_price)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        else:
            price = _current_avg(product_size)
        added = (Decimal(change) * price).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        product_size.quantity = old_qty + change
        product_size.stock_value = value + added
    else:
        remove = min(-change, old_qty)
        removed_value = (
            value * Decimal(remove) / Decimal(old_qty) if old_qty > 0 else Decimal("0.00")
        )
        product_size.quantity = old_qty - remove
        product_size.stock_value = (
            (value - removed_value) if product_size.quantity > 0 else Decimal("0.00")
        )

    new_qty = product_size.quantity
    logger.info(
        "adjust_stock product_id=%s size=%s %s->%s unit_price=%s reason=%s",
        product_size.product_id,
        product_size.size,
        old_qty,
        new_qty,
        unit_price,
        reason or "-",
    )
    if product_size.id and getattr(product_size, "woo_variation_id", None):
        from .woo_stock_reconcile import maybe_push_woo_stock

        maybe_push_woo_stock(product_size.id, quantity=new_qty)
    return old_qty, new_qty


def adjust_stock(
    product_id: int,
    size: str,
    *,
    set_to: Optional[int] = None,
    delta: Optional[int] = None,
    unit_price=None,
    reason: Optional[str] = None,
) -> Tuple[int, int]:
    """Skoryguj stan trzymajac spojnosc ``quantity`` i ``stock_value``.

    Podaj DOKLADNIE jedno z ``set_to`` (ustaw na wartosc) albo ``delta``
    (zmien o). ``unit_price`` ma znaczenie tylko przy zwiekszeniu stanu:
    - podane -> realny zakup, srednia sie przesuwa,
    - pominiete -> korekta po biezacej sredniej (neutralne).
    Zmniejszenie zawsze zdejmuje proporcjonalny udzial wartosci (po sredniej).

    Zwraca krotke ``(stary_stan, nowy_stan)``.
    """
    with get_session() as db:
        product_size = (
            db.query(ProductSize).filter_by(product_id=product_id, size=size).first()
        )
        if not product_size:
            raise ValueError(
                f"Brak ProductSize dla product_id={product_id} size={size}"
            )
        return apply_stock_adjustment(
            product_size,
            set_to=set_to,
            delta=delta,
            unit_price=unit_price,
            reason=reason,
        )


__all__ = ["adjust_stock", "apply_stock_adjustment"]
