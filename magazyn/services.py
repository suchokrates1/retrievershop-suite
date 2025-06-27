from __future__ import annotations
from typing import Dict, Tuple, Optional, List
import pandas as pd

from .db import get_session, record_purchase, consume_stock
from .models import Product, ProductSize
from .constants import ALL_SIZES


def create_product(name: str, color: str, quantities: Dict[str, int], barcodes: Dict[str, Optional[str]]):
    """Create a product with sizes and return the Product instance."""
    with get_session() as db:
        product = Product(name=name, color=color)
        db.add(product)
        db.flush()
        for size in ALL_SIZES:
            qty = int(quantities.get(size, 0))
            db.add(
                ProductSize(
                    product_id=product.id,
                    size=size,
                    quantity=qty,
                    barcode=barcodes.get(size),
                )
            )
    return product


def update_product(product_id: int, name: str, color: str, quantities: Dict[str, int], barcodes: Dict[str, Optional[str]]):
    """Update product details and size information."""
    with get_session() as db:
        product = db.query(Product).filter_by(id=product_id).first()
        if not product:
            return None
        product.name = name
        product.color = color
        for size in ALL_SIZES:
            qty = int(quantities.get(size, 0))
            barcode = barcodes.get(size)
            ps = db.query(ProductSize).filter_by(product_id=product_id, size=size).first()
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
    return product


def delete_product(product_id: int):
    """Remove product and its size information."""
    with get_session() as db:
        db.query(ProductSize).filter_by(product_id=product_id).delete()
        return db.query(Product).filter_by(id=product_id).delete()


def list_products() -> List[dict]:
    """Return products with their sizes for listing."""
    with get_session() as db:
        products = db.query(Product).all()
        result = []
        for p in products:
            sizes = {s.size: s.quantity for s in p.sizes}
            result.append({"id": p.id, "name": p.name, "color": p.color, "sizes": sizes})
    return result


def get_product_details(product_id: int) -> Tuple[Optional[dict], Dict[str, dict]]:
    """Return product basic info and size details."""
    with get_session() as db:
        row = db.query(Product).filter_by(id=product_id).first()
        product = None
        if row:
            product = {"id": row.id, "name": row.name, "color": row.color}
        sizes_rows = db.query(ProductSize).filter_by(product_id=product_id).all()
        product_sizes = {size: {"quantity": 0, "barcode": ""} for size in ALL_SIZES}
        for s in sizes_rows:
            product_sizes[s.size] = {"quantity": s.quantity, "barcode": s.barcode or ""}
    return product, product_sizes


def update_quantity(product_id: int, size: str, action: str):
    """Increase or decrease stock quantity for a specific size."""
    with get_session() as db:
        ps = db.query(ProductSize).filter_by(product_id=product_id, size=size).first()
        if ps:
            if action == "increase":
                ps.quantity += 1
            elif action == "decrease" and ps.quantity > 0:
                consume_stock(product_id, size, 1)


def find_by_barcode(barcode: str) -> Optional[dict]:
    """Return product information for the given barcode."""
    with get_session() as db:
        row = (
            db.query(Product.name, Product.color, ProductSize.size)
            .join(ProductSize)
            .filter(ProductSize.barcode == barcode)
            .first()
        )
        if row:
            name, color, size = row
            return {"name": name, "color": color, "size": size}
    return None


def get_products_for_delivery():
    """Return list of products with id, name and color."""
    with get_session() as db:
        return db.query(Product.id, Product.name, Product.color).all()


def record_delivery(product_id: int, size: str, quantity: int, price: float):
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
            .join(ProductSize, Product.id == ProductSize.product_id, isouter=True)
            .all()
        )
    return rows


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
                quantity = row.get(f"Ilość ({size})", 0)
                size_barcode = row.get(f"Barcode ({size})")
                ps = db.query(ProductSize).filter_by(product_id=product.id, size=size).first()
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

