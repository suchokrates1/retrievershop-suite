"""
Funkcje pomocnicze wspoldzielone przez modul allegro.

Wyodrebnione z allegro.py dla eliminacji duplikatow i lepszej czytelnosci.
"""
import json
from decimal import Decimal
from typing import Optional

from .models import Product, ProductSize


def format_decimal(value: Optional[Decimal]) -> Optional[str]:
    """Formatuj wartosc Decimal do wyswietlenia (2 miejsca po przecinku)."""
    if value is None:
        return None
    return f"{value:.2f}"


def build_offer_label(product: Optional[Product], size: Optional[ProductSize]) -> Optional[str]:
    """Zbuduj etykiete oferty na podstawie produktu i rozmiaru."""
    if not product:
        return None
    
    parts = [product.name]
    if product.color:
        parts.append(product.color)
    label = " ".join(parts)
    
    if size:
        label = f"{label} - {size.size}"
    
    return label


def build_inventory_list(db) -> list[dict]:
    """
    Zbuduj liste inventory (produkty + rozmiary) do dropdown/selecta.
    
    Uzywane w widokach ofert Allegro (offers, offers_and_prices).
    Zapobiega duplikowaniu ~60 linii kodu.
    
    Returns:
        Lista slownikow z kluczami: id, label, extra, filter, type, type_label
    """
    inventory_rows = (
        db.query(ProductSize, Product)
        .join(Product, ProductSize.product_id == Product.id)
        .order_by(Product.series, Product.category, Product.color, ProductSize.size)
        .all()
    )
    product_rows = db.query(Product).order_by(
        Product.series, Product.category, Product.color
    ).all()
    
    product_inventory: list[dict] = []
    size_inventory: list[dict] = []
    
    # Produkty (powiazanie na poziomie produktu)
    for product in product_rows:
        name_parts = [product.name]
        if product.color:
            name_parts.append(product.color)
        label = " ".join(name_parts)
        
        sizes = list(product.sizes or [])
        total_quantity = sum(
            s.quantity or 0 for s in sizes if s.quantity is not None
        )
        barcodes = sorted({s.barcode for s in sizes if s.barcode})
        
        extra_parts = ["Powiazanie na poziomie produktu"]
        if barcodes:
            extra_parts.append(f"EAN: {', '.join(barcodes)}")
        if sizes:
            extra_parts.append(f"Stan laczny: {total_quantity}")
        
        filter_values = [label, "produkt"]
        filter_values.extend(barcodes)
        if total_quantity:
            filter_values.append(str(total_quantity))
        
        product_inventory.append({
            "id": product.id,
            "label": label,
            "extra": ", ".join(extra_parts),
            "filter": " ".join(filter_values).strip().lower(),
            "type": "product",
            "type_label": "Produkt",
        })
    
    # Rozmiary (powiazanie na poziomie rozmiaru)
    for size, product in inventory_rows:
        name_parts = [product.name]
        if product.color:
            name_parts.append(product.color)
        main_label = " ".join(name_parts)
        label = f"{main_label} - {size.size}"
        
        extra_parts = []
        if size.barcode:
            extra_parts.append(f"EAN: {size.barcode}")
        quantity = size.quantity if size.quantity is not None else 0
        extra_parts.append(f"Stan: {quantity}")
        
        filter_text = " ".join([
            label,
            size.barcode or "",
            str(quantity),
            "rozmiar",
        ]).strip().lower()
        
        size_inventory.append({
            "id": size.id,
            "label": label,
            "extra": ", ".join(extra_parts),
            "filter": filter_text,
            "type": "size",
            "type_label": "Rozmiar",
        })
    
    return product_inventory + size_inventory
