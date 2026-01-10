from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import pandas as pd

from ..constants import ALL_SIZES, PRODUCT_CATEGORIES, PRODUCT_BRANDS, PRODUCT_SERIES
from ..db import get_session
from ..models import Product, ProductSize, PurchaseBatch

logger = logging.getLogger(__name__)
TWOPLACES = Decimal("0.01")


def _to_int(value) -> int:
    if value is None or pd.isna(value):
        return 0
    if isinstance(value, str):
        value = value.replace(" ", "").replace(",", "")
        if value == "":
            return 0
    return int(value)


def _to_decimal(value) -> Decimal:
    if value is None or pd.isna(value):
        return Decimal("0.00")
    if isinstance(value, str):
        value = value.replace(" ", "").replace(",", ".")
    try:
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as e:
        # Jeśli konwersja się nie powiedzie, zaloguj błąd i zwróć 0
        import logging
        logging.warning(f"Nie można skonwertować wartości '{value}' na Decimal: {e}")
        return Decimal("0.00")


def _clean_barcode(value) -> Optional[str]:
    """Return cleaned barcode string or None for empty/NaN values."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def create_product(
    category: str,
    brand: str,
    series: Optional[str],
    color: str,
    quantities: Dict[str, int],
    barcodes: Dict[str, Optional[str]],
):
    """Create a product with sizes and return the Product instance."""
    with get_session() as db:
        product = Product(
            category=category,
            brand=brand,
            series=series or None,
            color=color
        )
        db.add(product)
        db.flush()
        for size in ALL_SIZES:
            qty = _to_int(quantities.get(size, 0))
            db.add(
                ProductSize(
                    product_id=product.id,
                    size=size,
                    quantity=qty,
                    barcode=barcodes.get(size),
                )
            )
    return product


def update_product(
    product_id: int,
    category: str,
    brand: str,
    series: Optional[str],
    color: str,
    quantities: Dict[str, int],
    barcodes: Dict[str, Optional[str]],
    purchase_prices: Optional[Dict[str, Optional[float]]] = None,
):
    """Update product details and size information."""
    with get_session() as db:
        product = db.query(Product).filter_by(id=product_id).first()
        if not product:
            logger.warning(f"Product with ID {product_id} not found during update")
            return None
        
        logger.info(f"Updating product {product_id}: {category} {brand} {series} ({color})")
        product.category = category
        product.brand = brand
        product.series = series or None
        product.color = color
        for size in ALL_SIZES:
            qty = _to_int(quantities.get(size, 0))
            barcode = barcodes.get(size)
            ps = (
                db.query(ProductSize)
                .filter_by(product_id=product_id, size=size)
                .first()
            )
            if ps:
                ps.quantity = qty
                ps.barcode = barcode
            else:
                db.add(
                    ProductSize(
                        product_id=product_id,
                        size=size,
                        quantity=qty,
                        barcode=barcode,
                    )
                )
            
            # Update purchase price if provided
            if purchase_prices and size in purchase_prices:
                price = purchase_prices[size]
                if price is not None and price > 0:
                    # Check if there's already a batch for this size today
                    today = datetime.now().strftime("%Y-%m-%d")
                    existing_batch = (
                        db.query(PurchaseBatch)
                        .filter_by(product_id=product_id, size=size, purchase_date=today)
                        .first()
                    )
                    if existing_batch:
                        existing_batch.price = _to_decimal(price)
                    else:
                        # Create new batch with 0 quantity (just to store price)
                        db.add(
                            PurchaseBatch(
                                product_id=product_id,
                                size=size,
                                quantity=0,
                                price=_to_decimal(price),
                                purchase_date=today,
                            )
                        )
    return product


def delete_product(product_id: int):
    """Remove product and its size information."""
    with get_session() as db:
        db.query(ProductSize).filter_by(product_id=product_id).delete()
        return db.query(Product).filter_by(id=product_id).delete()


def list_products() -> List[dict]:
    """Return products with their sizes for listing, sorted by series, category, color."""
    with get_session() as db:
        # Sort by series, category, color
        products = db.query(Product).order_by(
            Product.series.asc(),
            Product.category.asc(),
            Product.color.asc()
        ).all()
        result = []
        for p in products:
            sizes = {s.size: s.quantity for s in p.sizes}
            result.append(
                {
                    "id": p.id,
                    "name": p.name,  # Full name via property
                    "display_name": p.display_name,  # Short display name
                    "category": p.category,
                    "brand": p.brand,
                    "series": p.series,
                    "color": p.color,
                    "sizes": sizes,
                }
            )
    return result


def get_product_details(
    product_id: int,
) -> Tuple[Optional[dict], Dict[str, dict]]:
    """Return product basic info and size details."""
    with get_session() as db:
        row = db.query(Product).filter_by(id=product_id).first()
        product = None
        if row:
            product = {
                "id": row.id,
                "name": row.name,
                "display_name": row.display_name,
                "category": row.category,
                "brand": row.brand,
                "series": row.series,
                "color": row.color
            }
        sizes_rows = db.query(ProductSize).filter_by(product_id=product_id).all()
        product_sizes = {
            size: {"quantity": 0, "barcode": "", "purchase_price": ""} for size in ALL_SIZES
        }
        for s in sizes_rows:
            # Get latest purchase price for this size
            latest_batch = (
                db.query(PurchaseBatch)
                .filter_by(product_id=product_id, size=s.size)
                .order_by(PurchaseBatch.purchase_date.desc())
                .first()
            )
            purchase_price = float(latest_batch.price) if latest_batch else ""
            
            product_sizes[s.size] = {
                "quantity": s.quantity,
                "barcode": s.barcode or "",
                "purchase_price": purchase_price,
            }
    return product, product_sizes


def find_by_barcode(barcode: str) -> Optional[dict]:
    """Return product information for the given barcode."""
    with get_session() as db:
        row = (
            db.query(
                Product.category,
                Product.brand,
                Product.series,
                Product.color,
                ProductSize.size,
                ProductSize.id
            )
            .join(ProductSize)
            .filter(ProductSize.barcode == barcode)
            .first()
        )
        if row:
            category, brand, series, color, size, product_size_id = row
            # Build name from new fields
            parts = [category or "Szelki", "dla psa"]
            if brand:
                parts.append(brand)
            if series:
                parts.append(series)
            name = " ".join(parts)
            
            return {
                "name": name,
                "category": category,
                "brand": brand,
                "series": series,
                "color": color,
                "size": size,
                "product_size_id": product_size_id,
            }
    return None


__all__ = [
    "_to_int",
    "_to_decimal",
    "_clean_barcode",
    "create_product",
    "update_product",
    "delete_product",
    "list_products",
    "get_product_details",
    "find_by_barcode",
]
