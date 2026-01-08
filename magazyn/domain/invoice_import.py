from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Dict, List

import pandas as pd
from pypdf import PdfReader

from ..constants import (
    ALL_SIZES,
    normalize_product_title_fragment,
    resolve_product_alias,
)
from ..db import get_session
from ..models import Product, ProductSize, PurchaseBatch
from .products import _clean_barcode, _to_decimal, _to_int

logger = logging.getLogger(__name__)


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
    i = 0
    while i < len(lines):
        m = re.match(r"(\d{1,2})([A-Za-z].*)", lines[i])
        if not m:
            i += 1
            continue
        name = m.group(2).strip()
        if i + 1 >= len(lines):
            break
        info = lines[i + 1]
        num_match = re.search(r"\d", info)
        if not num_match:
            i += 1
            continue
        prefix = info[: num_match.start()].strip()
        rest = info[num_match.start() :]
        tokens = (
            rest.replace("szt.", "")
            .replace("szt", "")
            .replace("%", "")
            .split()
        )
        if len(tokens) < 4:
            i += 1
            continue
        quantity = int(round(_num(tokens[0])))
        price = _num(tokens[3])
        color_parts = prefix.split()
        color = color_parts[-1] if color_parts else ""
        if len(color_parts) > 1:
            name = f"{name} {' '.join(color_parts[:-1])}".strip()

        size = ""
        barcode = ""
        if i + 2 < len(lines):
            line3 = lines[i + 2]
            m_size = re.search(r"Wariant:\s*([A-Za-z0-9]+)", line3)
            if m_size:
                size = m_size.group(1)
            m_bc = re.search(r"Kod kreskowy:\s*([0-9]+)", line3)
            if m_bc:
                barcode = m_bc.group(1)
        if i + 3 < len(lines):
            # skip repeated quantity line
            i += 4
        else:
            i += 3

        rows.append(
            {
                "Nazwa": name,
                "Kolor": color,
                "Rozmiar": size,
                "Ilość": quantity,
                "Cena": price,
                "Barcode": barcode,
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
                product = (
                    db.query(Product)
                    .filter_by(name=name, color=color)
                    .first()
                )
                if not product:
                    product = Product(name=name, color=color)
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
