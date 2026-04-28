"""Operacje zapisu zakupow, sprzedazy i FIFO magazynu."""

from __future__ import annotations

import datetime
from decimal import Decimal, ROUND_HALF_UP

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
    """Dodaj partie zakupu i zwieksz stan magazynowy."""
    purchase_date = purchase_date or datetime.datetime.now().strftime("%Y-%m-%d")
    with session_factory() as session:
        price = decimal_converter(price)
        session.add(
            PurchaseBatch(
                product_id=product_id,
                size=size,
                quantity=quantity,
                remaining_quantity=quantity,
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
) -> None:
    """Zapisz sprzedaz w istniejacej sesji."""
    sale_date = sale_date or datetime.datetime.now().isoformat()
    session.add(
        Sale(
            product_id=product_id,
            size=size,
            quantity=quantity,
            sale_date=sale_date,
            purchase_cost=decimal_converter(purchase_cost),
            sale_price=decimal_converter(sale_price),
            shipping_cost=decimal_converter(shipping_cost),
            commission_fee=decimal_converter(commission_fee),
        )
    )


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
) -> int:
    """Pobierz stan magazynowy metoda FIFO i zapisz sprzedaz."""
    with session_factory() as session:
        sale_price = decimal_converter(sale_price)
        shipping_cost = decimal_converter(shipping_cost)
        commission_fee = decimal_converter(commission_fee)
        product_size = session.query(ProductSize).filter_by(product_id=product_id, size=size).first()
        if not product_size:
            log.warning("Missing stock entry for product_id=%s size=%s", product_id, size)

        available = product_size.quantity if product_size else 0
        to_consume = min(available, quantity)
        batches = _purchase_batches(session, product_id, size)
        batches = _fallback_batches_by_barcode(session, product_id, size, product_size, batches, log)

        consumed, purchase_cost = _consume_batches(batches, to_consume)
        if consumed == 0 and to_consume > 0 and product_size and not batches:
            product_size.quantity -= to_consume
            consumed = to_consume
        elif consumed > 0 and product_size:
            product_size.quantity -= consumed
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
        )
        _log_consumed_stock(session, product_id, size, consumed, log)
    return consumed


def _purchase_batches(session, product_id, size):
    return (
        session.query(PurchaseBatch)
        .filter(PurchaseBatch.product_id == product_id, PurchaseBatch.size == size)
        .order_by(PurchaseBatch.purchase_date.asc(), PurchaseBatch.id.asc())
        .all()
    )


def _fallback_batches_by_barcode(session, product_id, size, product_size, batches, log):
    if any(batch.remaining_quantity and batch.remaining_quantity > 0 for batch in batches):
        return batches
    if not product_size or not product_size.barcode:
        return batches

    fallback_batches = (
        session.query(PurchaseBatch)
        .filter(
            PurchaseBatch.product_id == product_id,
            PurchaseBatch.barcode == product_size.barcode,
            PurchaseBatch.size != size,
        )
        .order_by(PurchaseBatch.purchase_date.asc(), PurchaseBatch.id.asc())
        .all()
    )
    if fallback_batches:
        log.info(
            "FIFO fallback: dopasowanie po barcode %s dla product_id=%s size=%s",
            product_size.barcode,
            product_id,
            size,
        )
        return fallback_batches
    return batches


def _consume_batches(batches, to_consume: int) -> tuple[int, Decimal]:
    remaining = to_consume
    purchase_cost = Decimal("0.00")
    for batch in batches:
        if remaining <= 0:
            break

        batch_available = batch.remaining_quantity if batch.remaining_quantity is not None else batch.quantity
        if batch_available <= 0:
            continue

        used = min(remaining, batch_available)
        if batch.remaining_quantity is not None:
            batch.remaining_quantity -= used
        else:
            batch.remaining_quantity = batch.quantity - used
        batch.quantity = max(0, batch.quantity - used)
        purchase_cost += used * batch.price
        remaining -= used
    return to_consume - remaining, purchase_cost


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