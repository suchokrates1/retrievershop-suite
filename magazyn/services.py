from __future__ import annotations
from typing import Dict, Tuple, Optional, List
import pandas as pd

from .db import get_session, record_purchase, consume_stock
from .models import Product, ProductSize, PurchaseBatch, Sale
from sqlalchemy import func
from .constants import ALL_SIZES
from datetime import datetime
from PyPDF2 import PdfReader
import logging
import io
import re


def _to_int(value) -> int:
    if value is None or pd.isna(value):
        return 0
    if isinstance(value, str):
        value = value.replace(" ", "").replace(",", "")
    return int(value)


def _to_float(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    if isinstance(value, str):
        value = value.replace(" ", "").replace(",", ".")
    return float(value)


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


logger = logging.getLogger(__name__)


def create_product(
    name: str,
    color: str,
    quantities: Dict[str, int],
    barcodes: Dict[str, Optional[str]],
):
    """Create a product with sizes and return the Product instance."""
    with get_session() as db:
        product = Product(name=name, color=color)
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
    name: str,
    color: str,
    quantities: Dict[str, int],
    barcodes: Dict[str, Optional[str]],
):
    """Update product details and size information."""
    with get_session() as db:
        product = db.query(Product).filter_by(id=product_id).first()
        if not product:
            return None
        product.name = name
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
            result.append(
                {"id": p.id, "name": p.name, "color": p.color, "sizes": sizes}
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
            product = {"id": row.id, "name": row.name, "color": row.color}
        sizes_rows = (
            db.query(ProductSize).filter_by(product_id=product_id).all()
        )
        product_sizes = {
            size: {"quantity": 0, "barcode": ""} for size in ALL_SIZES
        }
        for s in sizes_rows:
            product_sizes[s.size] = {
                "quantity": s.quantity,
                "barcode": s.barcode or "",
            }
    return product, product_sizes


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
                consume_stock(product_id, size, 1)
            elif action == "decrease":
                logger.warning(
                    "No stock to decrease for product_id=%s size=%s",
                    product_id,
                    size,
                )
        else:
            logger.warning(
                "Product id %s with size %s not found, quantity update skipped",
                product_id,
                size,
            )


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
            .join(
                ProductSize, Product.id == ProductSize.product_id, isouter=True
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
            product = (
                db.query(Product).filter_by(name=name, color=color).first()
            )
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
    lines_map: List[Tuple[float, List[Tuple[float, str]]]] = []
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
        column_pos = sorted({t[0] for _, line in sorted_lines for t in line})[
            :4
        ]

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
            price = _to_float(cols[3])
        except ValueError:
            continue
        size = cols[1]
        if size not in ALL_SIZES:
            logger.warning("Unexpected size '%s' in PDF row, skipping", size)
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
        return _to_float(val)

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


def _import_invoice_df(df: pd.DataFrame):
    """Record purchases using rows from a DataFrame."""
    for _, row in df.iterrows():
        name = row.get("Nazwa")
        color = row.get("Kolor", "")
        size = row.get("Rozmiar")
        quantity = _to_int(row.get("Ilość", 0))
        price = _to_float(row.get("Cena", 0))
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
                    db.query(Product).filter_by(name=name, color=color).first()
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
                    price=price,
                    purchase_date=datetime.now().isoformat(),
                )
            )
            ps.quantity += quantity


def import_invoice_rows(rows: List[Dict]):
    """Record purchases from a list of row dictionaries."""
    df = pd.DataFrame(rows)
    _import_invoice_df(df)


def import_invoice_file(file):
    """Parse uploaded invoice (Excel or PDF) and record purchases."""
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in {"xlsx", "xls"}:
        df = pd.read_excel(file)
    elif ext == "pdf":
        df = _parse_pdf(file)
    else:
        raise ValueError("Nieobsługiwany format pliku")

    _import_invoice_df(df)


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
            item.get("ean") or item.get("barcode") or item.get("sku") or ""
        ).strip()
        name = item.get("name")
        size = None
        color = None
        for attr in item.get("attributes", []):
            aname = (attr.get("name") or "").lower()
            if aname in {"rozmiar", "size"} and not size:
                size = attr.get("value")
            elif aname in {"kolor", "color"} and not color:
                color = attr.get("value")

        with get_session() as db:
            ps = None
            if barcode:
                ps = db.query(ProductSize).filter_by(barcode=barcode).first()
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

            if ps:
                consume_stock(ps.product_id, ps.size, qty)
            else:
                logger.warning(
                    "Unable to match product for order item: %s", item
                )


def get_sales_summary(days: int = 7) -> List[dict]:
    """Return sales summary for the given period."""
    start = datetime.now() - pd.Timedelta(days=days)
    with get_session() as db:
        rows = (
            db.query(
                Product.name,
                Product.color,
                Sale.size,
                func.sum(Sale.quantity).label("qty"),
            )
            .join(Product, Sale.product_id == Product.id)
            .filter(Sale.sale_date >= start.isoformat())
            .group_by(Sale.product_id, Sale.size)
            .all()
        )
        stock = {
            (ps.product_id, ps.size): ps.quantity
            for ps in db.query(ProductSize).all()
        }

    summary = []
    for name, color, size, qty in rows:
        remaining = stock.get(
            (
                db.query(Product).filter_by(name=name, color=color).first().id,
                size,
            ),
            0,
        )
        summary.append(
            {
                "name": name,
                "color": color,
                "size": size,
                "sold": int(qty or 0),
                "remaining": remaining,
            }
        )
    return summary
