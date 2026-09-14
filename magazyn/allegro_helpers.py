"""
Funkcje pomocnicze wspoldzielone przez modul allegro.

Wyodrebnione z allegro.py dla eliminacji duplikatow i lepszej czytelnosci.
"""
from decimal import Decimal
from typing import Optional

from .models.products import Product, ProductSize


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
    Zbuduj liste wariantow magazynowych (ProductSize) do dropdown/selecta.

    Uzywane w widoku ofert i cen Allegro (offers_and_prices). Dopasowanie
    ofert do magazynu odbywa sie WYLACZNIE po rozmiarze/SKU (ProductSize) -
    produkt to zestaw kilku wariantow rozmiarowych, wiec linkowanie na
    poziomie calego produktu byloby niejednoznaczne.

    Returns:
        Lista slownikow z kluczami: id, label, extra, filter
    """
    inventory_rows = (
        db.query(ProductSize, Product)
        .join(Product, ProductSize.product_id == Product.id)
        .order_by(Product.series, Product.category, Product.color, ProductSize.size)
        .all()
    )

    size_inventory: list[dict] = []
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
        ]).strip().lower()

        size_inventory.append({
            "id": size.id,
            "label": label,
            "extra": ", ".join(extra_parts),
            "filter": filter_text,
        })

    return size_inventory
