from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..constants import ALL_SIZES, SIZED_SIZES, UNIWERSALNY
from ..db import get_session
from ..models.products import Product, ProductSize

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


def validate_ean(ean: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Walidacja EAN (European Article Number).
    
    Args:
        ean: Kod EAN do walidacji
        
    Returns:
        Tuple (is_valid, error_message):
            - is_valid: True jeśli EAN jest poprawny lub None, False jeśli niepoprawny
            - error_message: None jeśli poprawny, komunikat błędu jeśli niepoprawny
    """
    # None lub pusty string jest dopuszczalny (produkty mogą nie mieć EAN)
    if ean is None or ean == "":
        return True, None
    
    # Sprawdzenie czy zawiera tylko cyfry
    if not ean.isdigit():
        return False, f"EAN '{ean}' zawiera niedozwolone znaki (dozwolone tylko cyfry)"
    
    # Sprawdzenie długości (tylko EAN-8 lub EAN-13)
    length = len(ean)
    if length not in (8, 13):
        return False, f"EAN '{ean}' ma nieprawidłową długość ({length} cyfr). Wymagane: 8 lub 13 cyfr"
    
    return True, None


SIZING_MODE_UNIVERSAL = "universal"
SIZING_MODE_SIZED = "sized"
SIZING_MODES = {SIZING_MODE_UNIVERSAL, SIZING_MODE_SIZED}


def applicable_sizes(sizing_mode: str) -> list[str]:
    if sizing_mode == SIZING_MODE_UNIVERSAL:
        return [UNIWERSALNY]
    if sizing_mode == SIZING_MODE_SIZED:
        return list(SIZED_SIZES)
    raise ValueError("Wybierz typ rozmiarów: Uniwersalny albo rozmiarowy.")


def infer_sizing_mode(product_sizes) -> str:
    """Infer a mode for legacy products when no explicit mode is stored."""
    active_sizes = {
        size.size
        for size in product_sizes
        if _to_int(getattr(size, "quantity", 0)) > 0 or getattr(size, "barcode", None)
    }
    if active_sizes == {UNIWERSALNY}:
        return SIZING_MODE_UNIVERSAL
    # Empty legacy products and conflicted products are intentionally shown as
    # sized: it is the non-destructive default and the UI will expose the
    # actual rows only after an explicit cleanup.
    return SIZING_MODE_SIZED


def _is_populated(quantity, barcode) -> bool:
    return _to_int(quantity) > 0 or bool((barcode or "").strip())


def validate_sizing(
    sizing_mode: str,
    quantities: Dict[str, int],
    barcodes: Dict[str, Optional[str]],
) -> None:
    """Reject any value or barcode outside the selected product size family."""
    allowed = set(applicable_sizes(sizing_mode))
    invalid = [
        size for size in ALL_SIZES
        if size not in allowed and _is_populated(quantities.get(size, 0), barcodes.get(size))
    ]
    if invalid:
        names = ", ".join(invalid)
        raise ValueError(
            f"Produkt typu {'uniwersalnego' if sizing_mode == SIZING_MODE_UNIVERSAL else 'rozmiarowego'} "
            f"nie może mieć danych dla rozmiarów: {names}."
        )


def has_mixed_sizing(
    quantities: Dict[str, int],
    barcodes: Optional[Dict[str, Optional[str]]] = None,
) -> bool:
    """Compatibility helper used by legacy callers."""
    barcodes = barcodes or {}
    return (
        _is_populated(quantities.get(UNIWERSALNY, 0), barcodes.get(UNIWERSALNY))
        and any(
            _is_populated(quantities.get(size, 0), barcodes.get(size))
            for size in SIZED_SIZES
        )
    )


def create_product(
    category: str,
    brand: str,
    series: Optional[str],
    color: str,
    quantities: Dict[str, int],
    barcodes: Dict[str, Optional[str]],
    sizing_mode: str = SIZING_MODE_SIZED,
):
    """Create a product with sizes and return the Product instance."""
    validate_sizing(sizing_mode, quantities, barcodes)
    # Walidacja wszystkich EAN przed utworzeniem produktu
    for size, barcode in barcodes.items():
        if barcode:
            is_valid, error_msg = validate_ean(barcode)
            if not is_valid:
                raise ValueError(f"Nieprawidłowy EAN dla rozmiaru {size}: {error_msg}")
    
    with get_session() as db:
        product = Product(
            category=category,
            brand=brand,
            series=series or None,
            color=color,
            sizing_mode=sizing_mode,
        )
        db.add(product)
        db.flush()
        for size in applicable_sizes(sizing_mode):
            qty = _to_int(quantities.get(size, 0))
            barcode = barcodes.get(size)
            # Nie tworz "widmowego" wiersza dla rozmiaru, ktorego produkt w
            # ogole nie uzywa (formularz zawsze wysyla wszystkie ALL_SIZES) -
            # inaczej kazdy produkt dostaje 8 wierszy ProductSize, wiekszosc
            # pustych, co lamie zalozenie "rozmiarowy albo Uniwersalny".
            if qty <= 0 and not barcode:
                continue
            db.add(
                ProductSize(
                    product_id=product.id,
                    size=size,
                    quantity=qty,
                    barcode=barcode,
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
    sizing_mode: Optional[str] = None,
):
    """Update product details and size information."""
    sizing_mode = sizing_mode or SIZING_MODE_SIZED
    validate_sizing(sizing_mode, quantities, barcodes)
    # Walidacja wszystkich EAN przed aktualizacją produktu
    for size, barcode in barcodes.items():
        if barcode:
            is_valid, error_msg = validate_ean(barcode)
            if not is_valid:
                raise ValueError(f"Nieprawidłowy EAN dla rozmiaru {size}: {error_msg}")
    
    from ..services.stock_adjust import apply_stock_adjustment

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
        current_mode = product.sizing_mode or infer_sizing_mode(product.sizes)
        if current_mode != sizing_mode:
            wrong_sizes = set(applicable_sizes(current_mode)) - set(applicable_sizes(sizing_mode))
            populated = [
                ps.size for ps in product.sizes
                if ps.size in wrong_sizes and _is_populated(ps.quantity, ps.barcode)
            ]
            if populated:
                raise ValueError(
                    "Nie można zmienić typu rozmiarów z aktywnym stanem lub kodem: "
                    + ", ".join(populated)
                )
        product.sizing_mode = sizing_mode
        for size in applicable_sizes(sizing_mode):
            qty = _to_int(quantities.get(size, 0))
            barcode = barcodes.get(size)

            # Cena zakupu (jesli podana) dotyczy sztuk DOKLADANYCH przy tej
            # edycji - traktujemy je jak realny zakup (srednia sie przesuwa).
            # Bez ceny zwiekszenie idzie po biezacej sredniej (neutralne).
            unit_price = None
            if purchase_prices and size in purchase_prices:
                raw_price = purchase_prices[size]
                if raw_price is not None and raw_price > 0:
                    unit_price = _to_decimal(raw_price)

            ps = (
                db.query(ProductSize)
                .filter_by(product_id=product_id, size=size)
                .first()
            )
            if not ps:
                # Nie tworz "widmowego" wiersza dla rozmiaru bez stanu i bez
                # kodu kreskowego - produkt ma byc albo rozmiarowy (XS-3XL),
                # albo Uniwersalny, nigdy oba jednoczesnie.
                if qty <= 0 and not barcode:
                    continue
                ps = ProductSize(
                    product_id=product_id,
                    size=size,
                    quantity=0,
                    stock_value=Decimal("0.00"),
                    barcode=barcode,
                )
                db.add(ps)
                db.flush()
            else:
                ps.barcode = barcode

            # Ustaw stan na podana ilosc utrzymujac spojnosc stock_value.
            apply_stock_adjustment(
                ps, set_to=qty, unit_price=unit_price, reason="edit_item"
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
                "color": row.color,
                "sizing_mode": row.sizing_mode or infer_sizing_mode(row.sizes),
            }
        sizes_rows = db.query(ProductSize).filter_by(product_id=product_id).all()
        product_sizes = {
            size: {"quantity": 0, "barcode": "", "purchase_price": ""} for size in ALL_SIZES
        }
        for s in sizes_rows:
            # Domyslna cena = biezaca srednia wazona zakupu (stock_value/quantity).
            # Zostawienie jej = korekta neutralna dla sredniej; wpisanie innej =
            # realny zakup, ktory przesuwa srednia.
            avg = float(s.avg_purchase_price) if s.avg_purchase_price is not None else ""

            product_sizes[s.size] = {
                "quantity": s.quantity,
                "barcode": s.barcode or "",
                "purchase_price": avg,
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
            
            # TTS - krotki format do odczytu glosowego
            # Produkty Uniwersalne (poza szelkami): "Kategoria kolor" 
            #   np. "Pas samochodowy rozowy", "Amortyzator czarny"
            # Produkty z rozmiarem: "Seria rozmiar kolor"
            #   np. "Front Line Premium M brazowy"
            if size == "Uniwersalny" and category and category.lower() != "szelki":
                tts_name = f"{category} {color}".strip() if color else category
            else:
                # Seria + rozmiar + kolor
                tts_parts = []
                if series:
                    tts_parts.append(series)
                if size and size != "Uniwersalny":
                    tts_parts.append(size)
                if color:
                    tts_parts.append(color)
                tts_name = " ".join(tts_parts) if tts_parts else name
            
            return {
                "name": name,
                "tts_name": tts_name,
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
    "validate_ean",
    "has_mixed_sizing",
    "create_product",
    "update_product",
    "delete_product",
    "list_products",
    "get_product_details",
    "find_by_barcode",
]
