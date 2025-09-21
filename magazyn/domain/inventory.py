from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

import pandas as pd

from ..config import settings
from ..constants import ALL_SIZES
from ..db import TWOPLACES, consume_stock, get_session, record_purchase, record_sale
from ..models import Product, ProductSize
from ..parsing import parse_product_info
from .products import _clean_barcode, _to_decimal, _to_int

logger = logging.getLogger(__name__)


def _calculate_shipping(amount: Decimal) -> Decimal:
    from ..sales import calculate_shipping

    return calculate_shipping(amount)


def update_quantity(product_id: int, size: str, action: str):
    """Increase or decrease stock quantity for a specific size."""
    with get_session() as db:
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=product_id, size=size)
            .first()
        )
        if ps:
            if action == "increase":
                ps.quantity += 1
            elif action == "decrease" and ps.quantity > 0:
                consume_stock(product_id, size, 1, sale_price=0)
            elif action == "decrease":
                logger.warning(
                    "No stock to decrease for product_id=%s size=%s",
                    product_id,
                    size,
                )
        else:
            logger.warning(
                "Product id %s size %s not found, quantity update skipped",
                product_id,
                size,
            )


def get_products_for_delivery():
    """Return list of products with id, name and color."""
    with get_session() as db:
        return db.query(Product.id, Product.name, Product.color).all()


def record_delivery(
    product_id: int,
    size: str,
    quantity: int,
    price: Decimal,
):
    """Record a delivery and update stock."""
    record_purchase(product_id, size, quantity, price)


def export_rows():
    """Return rows used for Excel export."""
    with get_session() as db:
        rows = (
            db.query(
                Product.name,
                Product.color,
                ProductSize.barcode,
                ProductSize.size,
                ProductSize.quantity,
            )
            .join(
                ProductSize,
                Product.id == ProductSize.product_id,
                isouter=True,
            )
            .all()
        )
    return rows


def get_product_sizes():
    """Return all product sizes joined with product information."""
    with get_session() as db:
        return (
            db.query(
                ProductSize.id.label("ps_id"),
                Product.id.label("product_id"),
                Product.name,
                Product.color,
                ProductSize.size,
            )
            .join(Product, ProductSize.product_id == Product.id)
            .all()
        )


def import_from_dataframe(df: pd.DataFrame):
    """Import products from a pandas DataFrame."""
    with get_session() as db:
        for _, row in df.iterrows():
            name = row["Nazwa"]
            color = row["Kolor"]
            product = db.query(Product).filter_by(name=name, color=color).first()
            if not product:
                product = Product(name=name, color=color)
                db.add(product)
                db.flush()
            for size in ALL_SIZES:
                quantity = _to_int(row.get(f"Ilość ({size})", 0))
                size_barcode = _clean_barcode(row.get(f"Barcode ({size})"))
                ps = (
                    db.query(ProductSize)
                    .filter_by(product_id=product.id, size=size)
                    .first()
                )
                if not ps:
                    db.add(
                        ProductSize(
                            product_id=product.id,
                            size=size,
                            quantity=quantity,
                            barcode=size_barcode,
                        )
                    )
                else:
                    ps.quantity = quantity
                    ps.barcode = size_barcode


def consume_order_stock(products: List[dict]):
    """Consume stock for products from a printed order."""
    for item in products or []:
        try:
            qty = _to_int(item.get("quantity", 0))
        except Exception:
            qty = 0
        if qty <= 0:
            continue
        barcode = str(
            item.get("ean")
            or item.get("barcode")
            or item.get("sku")
            or ""
        ).strip()
        name, size, color = parse_product_info(item)
        price = _to_decimal(item.get("price_brutto", 0))
        shipping_cost = _calculate_shipping(price)
        commission_fee = (
            price
            * Decimal(str(settings.COMMISSION_ALLEGRO))
            / Decimal("100")
        ).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        size = size or None
        color = color or None

        with get_session() as db:
            ps = None
            if barcode:
                ps = (
                    db.query(ProductSize)
                    .filter_by(barcode=barcode)
                    .first()
                )
            if not ps and name:
                query = (
                    db.query(ProductSize)
                    .join(Product, Product.id == ProductSize.product_id)
                    .filter(Product.name == name)
                )
                if color is not None:
                    query = query.filter(Product.color == color)
                if size is not None:
                    query = query.filter(ProductSize.size == size)
                ps = query.first()
                if ps and barcode and not ps.barcode:
                    ps.barcode = barcode
                    db.commit()

            if ps:
                consume_stock(
                    ps.product_id,
                    ps.size,
                    qty,
                    sale_price=price,
                    shipping_cost=shipping_cost,
                    commission_fee=commission_fee,
                )
            else:
                logger.warning(
                    "Unable to match product for order item: %s", item
                )
                placeholder = (
                    db.query(Product)
                    .filter_by(name="Unknown")
                    .first()
                )
                if not placeholder:
                    placeholder = Product(name="Unknown", color="")
                    db.add(placeholder)
                    db.flush()
                record_sale(
                    db,
                    placeholder.id,
                    size or "",
                    qty,
                    purchase_cost=Decimal("0.00"),
                    sale_price=Decimal("0.00"),
                    shipping_cost=Decimal("0.00"),
                    commission_fee=Decimal("0.00"),
                )


__all__ = [
    "update_quantity",
    "get_products_for_delivery",
    "record_delivery",
    "export_rows",
    "get_product_sizes",
    "import_from_dataframe",
    "consume_order_stock",
]
