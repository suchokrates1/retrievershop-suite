from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd
from pypdf import PdfReader

from ..constants import (
    ALL_SIZES,
    PRODUCT_CATEGORIES,
    PRODUCT_BRANDS,
    PRODUCT_SERIES,
    normalize_product_title_fragment,
    resolve_product_alias,
)
from ..db import get_session
from ..models import Product, ProductSize, PurchaseBatch
from .products import _clean_barcode, _to_decimal, _to_int, validate_ean

logger = logging.getLogger(__name__)


def parse_product_name_to_fields(name: str) -> Tuple[str, str, str]:
    """Parse product name string into (category, brand, series).
    
    Examples:
    - "Szelki dla psa Truelove Front Line Premium" -> ("Szelki", "Truelove", "Front Line Premium")
    - "Smycz dla psa Truelove Active" -> ("Smycz", "Truelove", "Active")
    - "Szelki Front Line Premium" -> ("Szelki", "Truelove", "Front Line Premium")
    
    Returns:
    - (category, brand, series) - category can be None if not recognized
    """
    name_lower = (name or "").lower()
    
    # Detect category - None if not recognized
    category = None
    if "smycz" in name_lower:
        category = "Smycz"
    elif "pas" in name_lower and ("bezpiecz" in name_lower or "samochodow" in name_lower):
        category = "Pas bezpieczeństwa"
    elif "obroża" in name_lower or "obroza" in name_lower:
        category = "Obroża"
    elif "szelki" in name_lower:
        category = "Szelki"
    
    # Detect brand (default Truelove)
    brand = "Truelove"
    known_brands_map = {
        "truelove": "Truelove",
        "julius-k9": "Julius-K9",
        "julius k9": "Julius-K9",
        "ruffwear": "Ruffwear",
        "hurtta": "Hurtta",
    }
    for pattern, brand_name in known_brands_map.items():
        if pattern in name_lower:
            brand = brand_name
            break
    
    # Detect series (order matters - more specific first)
    series = None
    series_patterns = [
        ("front line premium", "Front Line Premium"),
        ("front-line premium", "Front Line Premium"),
        ("frontline premium", "Front Line Premium"),
        ("fron line premium", "Front Line Premium"),
        ("frolin-prem", "Front Line Premium"),
        ("frolin prem", "Front Line Premium"),
        ("front line", "Front Line"),
        ("front-line", "Front Line"),
        ("frontline", "Front Line"),
        ("fron line", "Front Line"),
        ("frolin", "Front Line"),
        ("active", "Active"),
        ("blossom", "Blossom"),
        ("tropical", "Tropical"),
        ("tropic", "Tropical"),
        ("lumen", "Lumen"),
        ("amor", "Amor"),
        ("classic", "Classic"),
        ("neon", "Neon"),
        ("reflective", "Reflective"),
    ]
    
    for pattern, series_name in series_patterns:
        if pattern in name_lower:
            series = series_name
            break
    
    return category, brand, series


def _parse_simple_pdf(fh) -> pd.DataFrame:
    """Extract a simple table from a PDF invoice.

    The algorithm works by analysing text coordinates.
    """
    reader = PdfReader(fh)
    items = []
    for page in reader.pages:
        page_items = []

        def visitor(text, cm, tm, font_dict, font_size):
            txt = text.strip()
            if not txt:
                return
            x, y = tm[4], tm[5]
            page_items.append((x, y, txt))

        page.extract_text(visitor_text=visitor)
        items.extend(page_items)

    # group by y coordinate to lines
    lines_map: List[tuple[float, List[tuple[float, str]]]] = []
    for x, y, text in items:
        placed = False
        for idx, (ly, lst) in enumerate(lines_map):
            if abs(ly - y) < 5:
                lst.append((x, text))
                placed = True
                break
        if not placed:
            lines_map.append((y, [(x, text)]))

    # sort lines by y desc and text in each line by x
    sorted_lines = []
    for y, line in lines_map:
        line_sorted = sorted(line, key=lambda t: t[0])
        sorted_lines.append((y, line_sorted))
    sorted_lines.sort(key=lambda t: -t[0])

    # determine column x positions from first line with 4 items
    column_pos = None
    for _, line in sorted_lines:
        if len(line) >= 4:
            column_pos = [t[0] for t in line[:4]]
            break
    if not column_pos:
        # fallback to sorted unique x positions
        column_pos = sorted(
            {t[0] for _, line in sorted_lines for t in line}
        )[:4]

    rows = []
    for _, line in sorted_lines:
        cols: List[str] = ["", "", "", ""]
        for x, text in line:
            idx = min(
                range(len(column_pos)), key=lambda i: abs(column_pos[i] - x)
            )
            if cols[idx]:
                cols[idx] += f" {text}"
            else:
                cols[idx] = text
        if len(cols) < 4:
            continue
        try:
            qty = _to_int(cols[2])
            price = _to_decimal(cols[3])
        except ValueError:
            continue
        size = cols[1]
        if size not in ALL_SIZES:
            logger.warning(
                "Unexpected size '%s' in PDF row, skipping",
                size,
            )
            continue
        rows.append(
            {
                "Nazwa": cols[0],
                "Kolor": "",
                "Rozmiar": size,
                "Ilość": qty,
                "Cena": price,
                "Barcode": None,
            }
        )

    return pd.DataFrame(rows)


def _parse_tiptop_invoice(fh) -> pd.DataFrame:
    """Parse invoices produced by the Tip-Top accounting software."""
    reader = PdfReader(fh)
    lines: List[str] = []
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            lines.extend(t.strip() for t in txt.splitlines())

    def _num(val: str) -> float:
        return _to_decimal(val)

    rows = []
    
    # Join all lines to handle multiline entries
    full_text = "\n".join(lines)
    
    # Pattern for parsing invoice lines like:
    # "Szelki dla psa Truelove Tropical turkusowe 2,000 szt. 149,25 12 131,34 23% 213,56 49,12 262,68 Wariant: M"
    # or with barcode: "Kod kreskowy: 5903751102223"
    
    # Split by line numbers (1, 2, 3...) at start of lines
    entries = re.split(r'\n(?=\d{1,3}[A-Za-zŻżŹźĆćŁłÓóĄąĘęŚśŃń])', full_text)
    
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
            
        # Try parsing the combined format:
        # Name ... quantity szt. unit_price vat% ... Wariant: SIZE
        # Pattern: (Name) (qty,decimal) szt. (price,decimal) ... Wariant: (size)
        
        # Extract variant/size and SKU first
        # Format: Wariant: XL (TL-SZ-frolin-prem-XL-CZA) or Wariant: M, czarny (TL-SZ-active-M-CZA)
        size = ""
        color = ""
        sku = ""
        variant_match = re.search(r'Wariant:\s*([A-Za-z0-9]+)(?:,\s*([A-Za-zżźćńółęąśŻŹĆŃÓŁĘĄŚ]+))?\s*\(([^)]+)\)', entry, re.IGNORECASE)
        if variant_match:
            size = variant_match.group(1).strip()
            if variant_match.group(2):
                color = variant_match.group(2).strip()
            if variant_match.group(3):
                sku = variant_match.group(3).strip()
        else:
            # Fallback - variant without SKU
            variant_match_simple = re.search(r'Wariant:\s*([A-Za-z0-9]+)(?:,\s*([A-Za-zżźćńółęąśŻŹĆŃÓŁĘĄŚ]+))?', entry, re.IGNORECASE)
            if variant_match_simple:
                size = variant_match_simple.group(1).strip()
                if variant_match_simple.group(2):
                    color = variant_match_simple.group(2).strip()
        
        # Extract barcode
        barcode = ""
        barcode_match = re.search(r'Kod kreskowy:\s*(\d{8,13})', entry)
        if barcode_match:
            barcode = barcode_match.group(1)
        
        # Parse the main line: find quantity pattern (X,XXX szt.)
        qty_match = re.search(r'(\d{1,3})[,.](\d{3})\s*szt\.?', entry)
        if not qty_match:
            # Try simple number before szt.
            qty_match = re.search(r'(\d+)\s*szt\.?', entry)
        
        if not qty_match:
            continue
        
        # Quantity is the integer part (2,000 = 2)
        if ',' in entry[qty_match.start():qty_match.end()] or '.' in entry[qty_match.start():qty_match.end()]:
            quantity = int(qty_match.group(1))
        else:
            quantity = int(qty_match.group(1))
        
        # Name is everything before the quantity
        name_end = qty_match.start()
        name_part = entry[:name_end].strip()
        
        # Remove leading line number (e.g., "1", "2", "12")
        name_part = re.sub(r'^\d{1,3}(?=[A-Za-zŻżŹźĆćŁłÓóĄąĘęŚśŃń])', '', name_part).strip()
        
        # Extract color from name if present (last word that's a color)
        color_words = ['czarne', 'czarny', 'białe', 'biały', 'czerwone', 'czerwony', 
                       'niebieskie', 'niebieski', 'zielone', 'zielony', 'żółte', 'żółty',
                       'turkusowe', 'turkusowy', 'różowe', 'różowy', 'szare', 'szary',
                       'pomarańczowe', 'pomarańczowy', 'fioletowe', 'fioletowy', 'brązowe', 'brązowy']
        
        name_words = name_part.split()
        for word in reversed(name_words):
            if word.lower() in color_words:
                if not color:  # Only if not already set from Wariant
                    color = word
                name_words.remove(word)
                break
        
        name = ' '.join(name_words).strip()
        
        # Extract price - find numbers after "szt." 
        # Format: qty szt. Cena_brutto Rabat% Cena_po_rabacie St.VAT Wart_netto Wart_VAT Wart_brutto
        # Decimal numbers found: 59,25 (brutto) | 52,14 (po rabacie) | 254,34 (wart.netto) | ...
        # Rabat (12) is NOT captured because it has no decimal part
        # We want the SECOND decimal number = Cena brutto po rabacie (index 1)
        after_qty = entry[qty_match.end():].strip()
        
        # Find all decimal numbers in format XXX,XX or XXX.XX
        prices = re.findall(r'(\d{1,6})[,.](\d{2})\b', after_qty)
        
        price = 0.0
        if len(prices) >= 2:
            # Second price (index 1) is "Cena brutto po rabacie" (after discount)
            price = float(f"{prices[1][0]}.{prices[1][1]}")
        elif len(prices) >= 1:
            # Fallback to first price if only one found
            price = float(f"{prices[0][0]}.{prices[0][1]}")
        
        if not name or quantity <= 0:
            continue
        
        rows.append(
            {
                "Nazwa": name,
                "Kolor": color,
                "Rozmiar": size,
                "Ilość": quantity,
                "Cena": price,
                "Barcode": barcode,
                "SKU": sku,  # SKU from TipTop invoice (e.g. TL-SZ-frolin-prem-XL-CZA)
            }
        )

    return pd.DataFrame(rows)


def _parse_pdf(file) -> pd.DataFrame:
    """Parse PDF invoices in various formats."""
    data = file.read()
    file_obj = io.BytesIO(data)
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    file_obj.seek(0)
    if "Kod kreskowy" in text:
        return _parse_tiptop_invoice(file_obj)
    file_obj.seek(0)
    return _parse_simple_pdf(file_obj)


def _import_invoice_df(
    df: pd.DataFrame,
    invoice_number: str = None,
    supplier: str = None,
):
    """Record purchases using rows from a DataFrame.
    
    Args:
        df: DataFrame with columns: Nazwa, Kolor, Rozmiar, Ilość, Cena, Barcode
        invoice_number: Invoice/receipt number for tracking
        supplier: Supplier name
    """
    for _, row in df.iterrows():
        name = normalize_product_title_fragment(row.get("Nazwa", ""))
        name = resolve_product_alias(name)
        color = row.get("Kolor", "")
        size = row.get("Rozmiar")
        quantity = _to_int(row.get("Ilość", 0))
        price = _to_decimal(row.get("Cena", 0))
        barcode = _clean_barcode(row.get("Barcode"))
        
        # Walidacja EAN
        is_valid, error_msg = validate_ean(barcode)
        if not is_valid:
            logger.warning(f"Pomijam wiersz z niepoprawnym EAN: {error_msg}")
            logger.warning(f"  Produkt: {name}, Kolor: {color}, Rozmiar: {size}")
            continue
        
        # Parse name into structured fields
        category, brand, series = parse_product_name_to_fields(name)

        with get_session() as db:
            ps = None
            product = None
            if barcode:
                ps = (
                    db.query(ProductSize)
                    .filter_by(barcode=str(barcode))
                    .first()
                )
                if ps:
                    product = ps.product
                    size = ps.size

            if not product:
                # Try to find by new structured fields first
                product = (
                    db.query(Product)
                    .filter_by(category=category, brand=brand, series=series, color=color)
                    .first()
                )
                # Fallback: try by old name field for backward compatibility
                if not product:
                    product = (
                        db.query(Product)
                        .filter(Product._name == name, Product.color == color)
                        .first()
                    )
                if not product:
                    # If category was not detected, store original name in _name for backward compat
                    if category:
                        product = Product(
                            category=category,
                            brand=brand,
                            series=series,
                            color=color
                        )
                    else:
                        # Unknown product type - store original name
                        product = Product(
                            _name=name,
                            brand=brand,
                            color=color
                        )
                    db.add(product)
                    db.flush()

            ps = (
                db.query(ProductSize)
                .filter_by(product_id=product.id, size=size)
                .first()
            )
            if not ps:
                ps = ProductSize(
                    product_id=product.id,
                    size=size,
                    quantity=0,
                    barcode=barcode,
                )
                db.add(ps)
            elif barcode and not ps.barcode:
                ps.barcode = barcode

            db.add(
                PurchaseBatch(
                    product_id=product.id,
                    size=size,
                    quantity=quantity,
                    remaining_quantity=quantity,  # FIFO support
                    price=price,
                    purchase_date=datetime.now().isoformat(),
                    barcode=barcode,
                    invoice_number=invoice_number,
                    supplier=supplier,
                )
            )
            ps.quantity += quantity


def import_invoice_rows(
    rows: List[Dict],
    invoice_number: str = None,
    supplier: str = None,
):
    """Record purchases from a list of row dictionaries.
    
    Args:
        rows: List of dicts with keys: Nazwa, Kolor, Rozmiar, Ilość, Cena, Barcode
        invoice_number: Invoice/receipt number for tracking
        supplier: Supplier name
    """
    df = pd.DataFrame(rows)
    _import_invoice_df(df, invoice_number=invoice_number, supplier=supplier)


def import_invoice_file(file, invoice_number: str = None, supplier: str = None):
    """Parse uploaded invoice (Excel or PDF) and record purchases.
    
    Args:
        file: File object with filename attribute
        invoice_number: Optional override for invoice number
        supplier: Optional override for supplier name
    """
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in {"xlsx", "xls"}:
        df = pd.read_excel(file)
    elif ext == "pdf":
        df = _parse_pdf(file)
    else:
        raise ValueError("Nieobsługiwany format pliku")

    _import_invoice_df(df, invoice_number=invoice_number, supplier=supplier)


__all__ = [
    "_parse_simple_pdf",
    "_parse_tiptop_invoice",
    "_parse_pdf",
    "_import_invoice_df",
    "import_invoice_rows",
    "import_invoice_file",
]
