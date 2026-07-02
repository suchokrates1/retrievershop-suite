from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple

import pandas as pd
from pypdf import PdfReader

from ..constants import (
    ALL_SIZES,
    KNOWN_COLORS,
    normalize_product_title_fragment,
    resolve_product_alias,
)
from ..db import get_session
from ..models.products import Product, ProductSize, PurchaseBatch
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
    if "saszetk" in name_lower or "sakw" in name_lower or "torebk" in name_lower or "nerk" in name_lower:
        category = "Saszetki"
    elif "kamizelk" in name_lower:
        category = "Kamizelka"
    elif "kapok" in name_lower:
        category = "Kapok"
    elif "linka" in name_lower:
        category = "Linka"
    elif "smycz" in name_lower:
        category = "Smycz"
    elif "amortyzator" in name_lower:
        category = "Amortyzator"
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
        "hexa": "Hexa",
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
        ("front line premium cordura", "Front Line Cordura"),
        ("front line cordura", "Front Line Cordura"),
        ("frolin-cor", "Front Line Cordura"),
        ("frolin cor", "Front Line Cordura"),
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
        ("premium", "Premium"),  # Generic premium (e.g. Pas samochodowy Premium)
        ("active pro+", "Active Pro+"),
        ("active pro", "Active Pro+"),
        ("active", "Active"),
        ("blossom", "Blossom"),
        ("tropical", "Tropical"),
        ("tropic", "Tropical"),
        ("dive", "Dive"),
        ("chłodząca", "Chłodząca"),
        ("chlodzaca", "Chłodząca"),
        ("hexa (13mm, 5m)", "Treningowa wodoodporna 13mm 5m"),
        ("hexa 13mm 5m", "Treningowa wodoodporna 13mm 5m"),
        ("lumen", "Lumen"),
        ("amor", "Amor"),
        ("classic", "Classic"),
        ("neon", "Neon"),
        ("reflective", "Reflective"),
        ("dogi", "Dogi"),
        ("adventure soft", "Adventure Soft"),
        ("advsoft", "Adventure Soft"),
        ("adventure dog", "Adventure Dog"),
        ("adventure", "Adventure"),
        ("advent", "Adventure"),
        ("safe hiking", "Safe Hiking"),
        ("handy", "Handy"),
        ("outdoor", "Outdoor"),
        ("outdoo", "Outdoor"),
        ("security", "Security"),
        ("securi", "Security"),
        ("trail bag", "Trail Bag"),
        ("treat basic", "Treat Basic"),
        ("standard", "Standard"),
        ("v2", "V2"),
        ("v1", "V1"),
    ]
    
    for pattern, series_name in series_patterns:
        # Sprawdzaj całe wyrazy (word boundary), żeby "amor" nie trafił w "amortyzatorem"
        import re as _re
        if _re.search(r'(?<![a-z0-9])' + _re.escape(pattern) + r'(?![a-z0-9])', name_lower):
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


_SIZE_ALIASES = {"XXL": "2XL", "XXXL": "3XL"}

_KSEF_COLOR_CODE_MAP = {
    "BAN": "bananowy",
    "CZA": "czarny",
    "CZE": "czerwony",
    "KHA": "zielony-khaki",
    "LIL": "liliowy",
    "POM": "pomarańczowy",
    "ZOL": "żółty",
    "ŻOL": "żółty",
}


def _normalize_invoice_size(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    token = _SIZE_ALIASES.get(token, token)
    return token if token in ALL_SIZES else ""


def _size_from_sku(sku: str) -> str:
    for part in reversed(re.split(r"[-_/]", sku or "")):
        size = _normalize_invoice_size(part)
        if size:
            return size
    return ""


def _color_from_sku(sku: str) -> str:
    for part in reversed(re.split(r"[-_/]", sku or "")):
        color = _KSEF_COLOR_CODE_MAP.get(part.upper())
        if color:
            return color
    return ""


def _strip_trailing_color(value: str) -> Tuple[str, str]:
    text = re.sub(r"\s+", " ", value or "").strip()
    color_candidates = sorted(set(KNOWN_COLORS), key=len, reverse=True)
    for color in color_candidates:
        match = re.search(rf"(?i)(?:^|\s)({re.escape(color)})$", text)
        if match:
            name = text[: match.start(1)].strip(" ,")
            return name, match.group(1).casefold()
    return text, ""


def _parse_ksef_sku_map(lines: List[str]) -> Dict[int, Tuple[str, str]]:
    sku_map: Dict[int, Tuple[str, str]] = {}
    in_gtin_table = False
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line or "").strip()
        if not line:
            continue
        if line.startswith("Lp. GTIN"):
            in_gtin_table = True
            continue
        if not in_gtin_table or line.startswith("Wydruk pochodzi"):
            continue
        match = re.match(r"^(\d{1,3})\s+(\d{8,13})\s+(.+)$", line)
        if match:
            sku_map[int(match.group(1))] = (
                match.group(2).strip(),
                match.group(3).strip(),
            )
    return sku_map


def _parse_ksef_entries(lines: List[str]) -> List[str]:
    entries: List[str] = []
    current: List[str] = []
    in_products = False
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line or "").strip()
        if not line:
            continue
        if line == "Pozycje":
            in_products = True
            continue
        if line.startswith("Lp. GTIN"):
            break
        if not in_products:
            continue
        if line.startswith("Wydruk pochodzi"):
            continue
        if line.startswith(("Faktura wystawiona", "Lp. Nazwa", "podatku", "brutto")):
            continue
        if re.match(r"^\d{1,3}\s+", line):
            if current:
                entries.append(" ".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        entries.append(" ".join(current))
    return entries


def _parse_ksef_item(entry: str, sku_map: Dict[int, Tuple[str, str]]) -> Dict | None:
    match = re.match(
        r"^(?P<lp>\d{1,3})\s+"
        r"(?P<body>.+?)"
        r"(?P<unit_price>\d{1,6}\.\d{2})\s+"
        r"(?P<qty>\d+)\s+szt\s+"
        r"(?P<discount>\d{1,6}(?:\.\d{1,2})?)\s+23%\s+"
        r"(?P<total>\d{1,8}(?:\.\d{1,2})?)$",
        entry,
    )
    if not match:
        logger.warning("Nie rozpoznano pozycji KSeF: %s", entry)
        return None

    lp = int(match.group("lp"))
    barcode, sku = sku_map.get(lp, ("", ""))
    quantity = int(match.group("qty"))
    total = _to_decimal(match.group("total"))
    price = Decimal("0.00")
    if quantity > 0:
        price = (total / Decimal(quantity)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    body = re.sub(r"\s+", " ", match.group("body")).strip()
    size = _size_from_sku(sku)
    color = ""

    name_part = body
    if ">" in body:
        name_part, variant_part = body.rsplit(">", 1)
        variant_size = re.match(r"\s*([A-Za-z0-9]+)", variant_part or "")
        if variant_size:
            size = _normalize_invoice_size(variant_size.group(1)) or size
        _, variant_color = _strip_trailing_color(variant_part)
        color = variant_color

    name, trailing_color = _strip_trailing_color(name_part)
    color = trailing_color or color or _color_from_sku(sku)
    if not size:
        size = "Uniwersalny"

    return {
        "Nazwa": name,
        "Kolor": color,
        "Rozmiar": size,
        "Ilość": quantity,
        "Cena": float(price),
        "Barcode": barcode,
        "SKU": sku,
    }


def _parse_ksef_text(text: str) -> pd.DataFrame:
    lines = [line.strip() for line in (text or "").splitlines()]
    sku_map = _parse_ksef_sku_map(lines)
    rows = []
    for entry in _parse_ksef_entries(lines):
        row = _parse_ksef_item(entry, sku_map)
        if row:
            rows.append(row)
    return pd.DataFrame(rows)


def _parse_ksef_invoice(fh) -> pd.DataFrame:
    reader = PdfReader(fh)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_ksef_text(text)


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
        
        # --- Ekstrakcja SKU, wariantu, kodu kreskowego ---
        # Usun znaki nowej linii zeby polaczyc przerwane wpisy
        entry_joined = entry.replace('\n', ' ')
        
        size = ""
        color = ""
        sku = ""
        
        # 1. SKU - szukaj wzorca TL-XX-... (niezaleznie od nawiasow)
        sku_match = re.search(r'TL-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+', entry_joined)
        if sku_match:
            sku = sku_match.group(0).strip()
        
        # 2. Wariant - obsluguje oba formaty:
        #    "Wariant: XL, czarny" (rozmiar pierwszy)
        #    "Wariant: żółty, XL" (kolor pierwszy - polskie znaki!)
        #    "Wariant: czarny, L"  (kolor pierwszy - ASCII)
        #    "Wariant:3XL, limonkowy" (bez spacji po dwukropku)
        #    "Wariant: XXXL (60-65 cm)" (rozmiar z zakresem cm)
        _PL = r'A-Za-z0-9żźćńółęąśŻŹĆŃÓŁĘĄŚ'
        variant_match = re.search(
            r'Wariant:\s*([' + _PL + r']+)'
            r'(?:\s*\(\d+-\d+\s*cm\))?'           # opcjonalny (XX-YY cm) - pomijamy
            r'(?:,\s*([' + _PL + r']+))?',
            entry_joined, re.IGNORECASE
        )
        if variant_match:
            token1 = variant_match.group(1).strip()
            token2 = variant_match.group(2).strip() if variant_match.group(2) else ""
            
            # Normalizacja rozmiarow: XXL->2XL, XXXL->3XL
            _size_aliases = {'XXL': '2XL', 'XXXL': '3XL'}
            token1_norm = _size_aliases.get(token1.upper(), token1.upper())
            token2_norm = _size_aliases.get(token2.upper(), token2.upper()) if token2 else ""
            
            # Wykryj ktory token to rozmiar a ktory kolor
            if token1_norm in ALL_SIZES:
                size = token1_norm
                color = token2
            elif token2_norm and token2_norm in ALL_SIZES:
                size = token2_norm
                color = token1
            else:
                # Probuj odczytac rozmiar z SKU
                if sku:
                    for part in sku.split('-'):
                        p_norm = _size_aliases.get(part.upper(), part.upper())
                        if p_norm in ALL_SIZES:
                            size = p_norm
                            # Ustaw kolor na ten token ktory nie jest rozmiarem
                            color = token1 if token2_norm == p_norm else token2 if token1_norm == p_norm else token1
                            break
                if not size:
                    # Sprawdz czy token1 to znany kolor a nie rozmiar
                    from ..constants import KNOWN_COLORS
                    _known_color_lower = {c.lower() for c in KNOWN_COLORS}
                    if token1.lower() in _known_color_lower:
                        # Token1 to kolor, rozmiar zostaje pusty (domyslnie Uniwersalny)
                        color = token1
                    else:
                        # Ostatnia szansa - pierwszy token jako rozmiar
                        size = token1
                        color = token2
        
        # 3. Kod kreskowy - bierz ostatni (wariantowy jest bardziej specyficzny niz produktowy)
        barcode = ""
        barcode_matches = re.findall(r'Kod kreskowy:\s*(\d{8,13})', entry)
        if barcode_matches:
            barcode = barcode_matches[-1]
        
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
        color_words = ['czarne', 'czarny', 'czarna', 'białe', 'biały', 'biała',
                       'czerwone', 'czerwony', 'czerwona',
                       'niebieskie', 'niebieski', 'niebieska',
                       'zielone', 'zielony', 'zielona',
                       'żółte', 'żółty', 'żółta',
                       'turkusowe', 'turkusowy', 'turkusowa',
                       'różowe', 'różowy', 'różowa', 'róż',
                       'szare', 'szary', 'szara',
                       'pomarańczowe', 'pomarańczowy', 'pomarańczowa',
                       'fioletowe', 'fioletowy', 'fioletowa', 'fiolet',
                       'brązowe', 'brązowy', 'brązowa',
                       'limonkowe', 'limonkowy', 'limonkowa',
                       'liliowe', 'liliowy', 'liliowa',
                       'khaki', 'zielony-khaki',
                       'stalowa róż', 'stalowa różowa', 'stalowa zieleń']
        # Kolory dwuwyrazowe - lista do sprawdzenia przed petla po slowach
        _two_word_colors = ['stalowa róż', 'stalowa różowa', 'stalowa zieleń', 'zielony-khaki']
        
        name_words = name_part.split()
        # Sprawdz kolory dwuwyrazowe na koncu nazwy
        if not color and len(name_words) >= 2:
            two_word = f"{name_words[-2]} {name_words[-1]}".lower()
            if two_word in _two_word_colors:
                color = f"{name_words[-2]} {name_words[-1]}"
                name_words = name_words[:-2]
        # Jesli nie znaleziono dwuwyrazowego, szukaj jednowyrazowego
        if not color:
            for word in reversed(name_words):
                if word.lower() in color_words:
                    color = word
                    name_words.remove(word)
                    break
        # Normalizuj kolory zlozone -> prosty kolor
        _color_normalize = {
            'zielony-khaki': 'zielony', 'khaki': 'zielony',
            'stalowa roz': 'różowy', 'stalowa rozowa': 'różowy',
            'stalowa róż': 'różowy',
            'stalowa zieleń': 'zielony', 'stalowa zielen': 'zielony',
            'żółta': 'żółty', 'żółte': 'żółty',
            'liliowa': 'liliowy', 'liliowe': 'liliowy',
            'pomarańczowa': 'pomarańczowy', 'pomarańczowe': 'pomarańczowy',
            'czarne': 'czarny', 'czarna': 'czarny',
            'różowe': 'różowy', 'różowa': 'różowy',
        }
        color = _color_normalize.get(color.lower(), color)
        
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


def _extract_invoice_metadata(text: str) -> Tuple[str, str, str | None]:
    """Extract invoice number, supplier and delivery date from PDF text."""
    invoice_number = None
    supplier = None
    delivery_date = None
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if line == "Numer faktury" and idx + 1 < len(lines):
            next_line = lines[idx + 1]
            number_match = re.match(r"([A-Z]{1,10}\s+\d{4}/\d{2}/\d{6})", next_line)
            if number_match:
                invoice_number = number_match.group(1).strip()
        if line == "Sprzedawca":
            for supplier_line in lines[idx + 1 : idx + 8]:
                if supplier_line.startswith("Nazwa:"):
                    supplier = supplier_line.split(":", 1)[1].strip()
                    break
        if invoice_number and supplier:
            break

    delivery_match = re.search(
        r"Data dostawy:\s*(\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if delivery_match:
        delivery_date = delivery_match.group(1)
    
    # Szukaj numeru faktury: "Faktura FS 2026/02/000006" lub "Faktura VAT 123/2026"
    invoice_match = re.search(r'Faktura\s+(?:FS|VAT)?\s*([A-Z0-9/-]+)', text, re.IGNORECASE)
    if not invoice_number and invoice_match:
        invoice_number = invoice_match.group(1).strip()
    
    # Szukaj dostawcy - TipTop format ma strukture:
    # "Sprzedawca\nNabywca / Platnik\nTIP-TOP Agnieszka Pawlicka\n..."
    # Czyli sprzedawca jest w trzeciej linii po "Sprzedawca"
    # Szukamy firmy przed NIP (format: "Nazwa firmy\nAdres\nKod Miasto\nNIP: xxx")
    
    # Proba 1: TipTop - szukaj nazwy przed pierwszym NIP
    tiptop_match = re.search(r'Nabywca[^\n]*\n([A-ZŻŹĆŃÓŁĘĄŚ][A-Za-zżźćńółęąśŻŹĆŃÓŁĘĄŚ\s\-]+?)(?:\n|Retriever)', text)
    if not supplier and tiptop_match:
        supplier = tiptop_match.group(1).strip()
    elif not supplier:
        # Proba 2: Standardowy format - po "Sprzedawca"
        supplier_match = re.search(r'Sprzedawca[\s\n]+([^\n]+?)(?:\n|ul\.|NIP)', text)
        if supplier_match:
            candidate = supplier_match.group(1).strip()
            # Ignoruj naglowki kolumn
            if candidate not in ('Nabywca / Platnik', 'Nabywca', 'Odbiorca'):
                supplier = candidate
    
    return invoice_number, supplier, delivery_date


def _parse_pdf(file) -> Tuple[pd.DataFrame, str, str, str | None]:
    """Parse PDF invoices in various formats.

    Returns:
        Tuple of (DataFrame, invoice_number, supplier, delivery_date)
    """
    data = file.read()
    file_obj = io.BytesIO(data)
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # Wyciagnij metadane faktury
    invoice_number, supplier, delivery_date = _extract_invoice_metadata(text)

    file_obj.seek(0)
    if "Numer KSeF" in text or "Lp. GTIN Indeks" in text:
        df = _parse_ksef_text(text)
    elif "Kod kreskowy" in text:
        df = _parse_tiptop_invoice(file_obj)
    else:
        file_obj.seek(0)
        df = _parse_simple_pdf(file_obj)

    return df, invoice_number, supplier, delivery_date


def _import_invoice_df(
    df: pd.DataFrame,
    invoice_number: str = None,
    supplier: str = None,
    delivery_date: str | None = None,
):
    """Record purchases using rows from a DataFrame.

    Args:
        df: DataFrame with columns: Nazwa, Kolor, Rozmiar, Ilość, Cena, Barcode
        invoice_number: Invoice/receipt number for tracking
        supplier: Supplier name
        delivery_date: Delivery date (YYYY-MM-DD), defaults to today
    """
    if not delivery_date:
        delivery_date = datetime.now().strftime('%Y-%m-%d')
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

            # Jesli size jest pusty, probuj znalezc jedyny ProductSize dla tego produktu
            if not size and product:
                sole_ps = (
                    db.query(ProductSize)
                    .filter_by(product_id=product.id)
                    .all()
                )
                if len(sole_ps) == 1:
                    size = sole_ps[0].size
                    logger.info(
                        "Uzupelniono pusty rozmiar na '%s' dla product_id=%s",
                        size, product.id,
                    )

            # Domyslny rozmiar Uniwersalny gdy brak rozmiaru po todas probach
            if not size:
                size = "Uniwersalny"
                logger.info(
                    "Ustawiono domyslny rozmiar 'Uniwersalny' dla product_id=%s",
                    product.id if product else "?",
                )

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

            # Sprawdz czy taki batch juz istnieje (ochrona przed duplikatami)
            existing_batch = (
                db.query(PurchaseBatch)
                .filter_by(
                    product_id=product.id,
                    size=size,
                    quantity=quantity,
                    price=price,
                    purchase_date=delivery_date,
                    invoice_number=invoice_number,
                )
                .first()
            )
            if existing_batch:
                logger.info(
                    f"Pomijam duplikat batcha: product={product.id} "
                    f"size={size} qty={quantity} invoice={invoice_number}"
                )
                continue

            db.add(
                PurchaseBatch(
                    product_id=product.id,
                    size=size,
                    quantity=quantity,
                    price=price,
                    purchase_date=delivery_date,
                    barcode=barcode,
                    invoice_number=invoice_number,
                    supplier=supplier,
                )
            )
            ps.quantity += quantity
            # Podnies wartosc magazynu (srednia wazona) o wartosc dostawy.
            ps.stock_value = Decimal(str(ps.stock_value or 0)) + Decimal(quantity) * Decimal(str(price))


def import_invoice_rows(
    rows: List[Dict],
    invoice_number: str = None,
    supplier: str = None,
    delivery_date: str | None = None,
):
    """Record purchases from a list of row dictionaries.

    Args:
        rows: List of dicts with keys: Nazwa, Kolor, Rozmiar, Ilość, Cena, Barcode
        invoice_number: Invoice/receipt number for tracking
        supplier: Supplier name
        delivery_date: Delivery date (YYYY-MM-DD)
    """
    df = pd.DataFrame(rows)
    _import_invoice_df(
        df,
        invoice_number=invoice_number,
        supplier=supplier,
        delivery_date=delivery_date,
    )


def import_invoice_file(file, invoice_number: str = None, supplier: str = None):
    """Parse uploaded invoice (Excel or PDF) and record purchases.

    Args:
        file: File object with filename attribute
        invoice_number: Optional override for invoice number
        supplier: Optional override for supplier name
    """
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower()
    delivery_date = None
    if ext in {"xlsx", "xls"}:
        df = pd.read_excel(file)
    elif ext == "pdf":
        df, pdf_invoice_number, pdf_supplier, delivery_date = _parse_pdf(file)
        # Użyj danych z PDF jeśli nie podano nadpisania
        if not invoice_number:
            invoice_number = pdf_invoice_number
        if not supplier:
            supplier = pdf_supplier
    else:
        raise ValueError("Nieobsługiwany format pliku")

    _import_invoice_df(
        df,
        invoice_number=invoice_number,
        supplier=supplier,
        delivery_date=delivery_date,
    )


__all__ = [
    "_parse_simple_pdf",
    "_parse_tiptop_invoice",
    "_parse_ksef_invoice",
    "_parse_ksef_text",
    "_parse_pdf",
    "_import_invoice_df",
    "import_invoice_rows",
    "import_invoice_file",
]
