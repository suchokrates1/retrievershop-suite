"""Operacje zapisu zakupow i sprzedazy - wycena metoda sredniej wazonej (AVCO).

Model wyceny: kazdy ``ProductSize`` trzyma ``quantity`` (liczba sztuk) oraz
``stock_value`` (laczna wartosc zakupu tych sztuk). Srednia cena zakupu =
``stock_value / quantity`` liczona w locie. Przyjecie towaru podnosi wartosc,
sprzedaz zdejmuje proporcjonalny udzial wartosci (dzieki czemu sprzedaz calego
stanu zeruje ``stock_value`` co do grosza). ``PurchaseBatch`` sluzy juz tylko
jako dziennik dostaw (historia/raporty), nie do wyceny.
"""

from __future__ import annotations

import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from ..models.products import Product, ProductSize, PurchaseBatch, Sale


def record_purchase(
    product_id,
    size,
    quantity,
    price,
    *,
    session_factory,
    decimal_converter,
    purchase_date=None,
    barcode=None,
    invoice_number=None,
    supplier=None,
    notes=None,
) -> None:
    """Dodaj wpis dostawy (historia) i podnies stan oraz wartosc magazynu."""
    purchase_date = purchase_date or datetime.datetime.now().strftime("%Y-%m-%d")
    with session_factory() as session:
        price = decimal_converter(price)
        session.add(
            PurchaseBatch(
                product_id=product_id,
                size=size,
                quantity=quantity,
                price=price,
                purchase_date=purchase_date,
                barcode=barcode,
                invoice_number=invoice_number,
                supplier=supplier,
                notes=notes,
            )
        )
        product_size = session.query(ProductSize).filter_by(product_id=product_id, size=size).first()
        if product_size:
            product_size.quantity += quantity
            current_value = Decimal(str(product_size.stock_value or 0))
            product_size.stock_value = current_value + Decimal(quantity) * price
            size_id = product_size.id
            new_qty = product_size.quantity
            woo_vid = product_size.woo_variation_id
        else:
            size_id = None
            new_qty = None
            woo_vid = None

    if size_id and woo_vid:
        from .woo_stock_reconcile import maybe_push_woo_stock

        maybe_push_woo_stock(size_id, quantity=new_qty)


def record_sale(
    session,
    product_id,
    size,
    quantity,
    *,
    decimal_converter,
    purchase_cost=Decimal("0.00"),
    sale_price=Decimal("0.00"),
    shipping_cost=Decimal("0.00"),
    commission_fee=Decimal("0.00"),
    sale_date=None,
    order_id: Optional[str] = None,
) -> Sale:
    """Zapisz sprzedaz w istniejacej sesji.

    ``order_id`` pozwala pozniej policzyc REALNY koszt zakupu dla zamowienia
    (suma ``purchase_cost`` ze sprzedazy tego zamowienia) oraz - w razie zwrotu -
    odtworzyc koszt sztuki, zeby oddac dokladnie tyle wartosci ile zeszlo
    (patrz FinancialCalculator.get_purchase_cost_for_order i
    services/return_stock.py).
    """
    sale_date = sale_date or datetime.datetime.now().isoformat()
    sale = Sale(
        product_id=product_id,
        size=size,
        quantity=quantity,
        sale_date=sale_date,
        purchase_cost=decimal_converter(purchase_cost),
        sale_price=decimal_converter(sale_price),
        shipping_cost=decimal_converter(shipping_cost),
        commission_fee=decimal_converter(commission_fee),
        order_id=order_id,
    )
    session.add(sale)
    return sale


def consume_stock(
    product_id,
    size,
    quantity,
    *,
    session_factory,
    decimal_converter,
    twoplaces,
    low_stock_threshold,
    stock_alert_sender,
    log,
    sale_price=Decimal("0.00"),
    shipping_cost=Decimal("0.00"),
    commission_fee=Decimal("0.00"),
    order_id: Optional[str] = None,
) -> int:
    """Zdejmij stan magazynowy i zapisz sprzedaz z kosztem wg sredniej wazonej.

    Koszt zakupu sprzedanych sztuk = proporcjonalny udzial ``stock_value``
    (``stock_value * consumed / available``). Zdjecie calego stanu zeruje
    ``stock_value``. ``order_id`` (jesli podany) laczy sprzedaz z zamowieniem.
    """
    with session_factory() as session:
        sale_price = decimal_converter(sale_price)
        shipping_cost = decimal_converter(shipping_cost)
        commission_fee = decimal_converter(commission_fee)
        product_size = session.query(ProductSize).filter_by(product_id=product_id, size=size).first()
        if not product_size:
            log.warning("Missing stock entry for product_id=%s size=%s", product_id, size)

        available = product_size.quantity if product_size else 0
        to_consume = min(available, quantity)
        purchase_cost = Decimal("0.00")
        consumed = 0

        size_id = product_size.id if product_size else None
        woo_vid = product_size.woo_variation_id if product_size else None
        new_qty = None

        if to_consume > 0 and product_size:
            stock_value = Decimal(str(product_size.stock_value or 0))
            # Proporcjonalny udzial wartosci - zdjecie calego stanu (to_consume
            # == available) daje dokladnie cala wartosc, wiec reszta = 0.
            purchase_cost = stock_value * Decimal(to_consume) / Decimal(available)
            product_size.quantity -= to_consume
            remaining_value = stock_value - purchase_cost
            product_size.stock_value = (
                remaining_value if product_size.quantity > 0 else Decimal("0.00")
            )
            consumed = to_consume
            new_qty = product_size.quantity
            _send_low_stock_alert(
                session,
                product_id,
                size,
                product_size.quantity,
                low_stock_threshold,
                stock_alert_sender,
                log,
            )

        if consumed < quantity:
            log.warning(
                "Insufficient stock for product_id=%s size=%s: requested=%s consumed=%s",
                product_id,
                size,
                quantity,
                consumed,
            )

        record_sale(
            session,
            product_id,
            size,
            quantity,
            decimal_converter=decimal_converter,
            purchase_cost=purchase_cost.quantize(twoplaces, rounding=ROUND_HALF_UP),
            sale_price=sale_price,
            shipping_cost=shipping_cost,
            commission_fee=commission_fee,
            order_id=order_id,
        )
        _log_consumed_stock(session, product_id, size, consumed, log)

    if size_id and woo_vid and new_qty is not None:
        from .woo_stock_reconcile import maybe_push_woo_stock

        maybe_push_woo_stock(size_id, quantity=new_qty)
    return consumed


def _send_low_stock_alert(
    session,
    product_id,
    size,
    quantity,
    low_stock_threshold,
    stock_alert_sender,
    log,
) -> None:
    if quantity >= low_stock_threshold:
        return
    try:
        product = session.query(Product).filter_by(id=product_id).first()
        name = product.name if product else str(product_id)
        stock_alert_sender(name, size, quantity)
    except Exception as exc:
        log.error("Low stock alert failed: %s", exc)


def _log_consumed_stock(session, product_id, size, consumed: int, log) -> None:
    if consumed <= 0:
        return
    product = session.query(Product).filter_by(id=product_id).first()
    name = product.name if product else str(product_id)
    log.info("Pobrano z magazynu: %s %s x%s", name, size, consumed)


__all__ = ["consume_stock", "record_purchase", "record_sale"]
