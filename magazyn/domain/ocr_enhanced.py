"""Enhanced OCR module for invoice parsing.

Uses multiple strategies:
1. pypdf for text-based PDFs
2. pdf2image + Tesseract for scanned PDFs
3. Image preprocessing for better OCR accuracy
"""
from __future__ import annotations

import io
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Try to import optional OCR dependencies
try:
    from PIL import Image, ImageEnhance, ImageFilter
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    logger.warning("Pillow not available - image preprocessing disabled")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not available - OCR fallback disabled")

try:
    import pdf2image
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not available - scanned PDF support disabled")


@dataclass
class InvoiceItem:
    """Parsed invoice item."""
    name: str
    color: str
    size: str
    quantity: int
    price: Decimal
    barcode: Optional[str] = None
    raw_text: Optional[str] = None  # Original text for debugging


@dataclass
class ParsedInvoice:
    """Parsed invoice data."""
    items: List[InvoiceItem]
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    supplier: Optional[str] = None
    total_amount: Optional[Decimal] = None
    raw_text: Optional[str] = None  # Full OCR text for debugging


# EAN pattern: 8 or 13 digits
EAN_PATTERN = re.compile(r'\b(\d{8}|\d{13})\b')

# Price patterns (Polish format: 123,45 or 123.45)
PRICE_PATTERN = re.compile(r'(\d{1,6})[,.](\d{2})\b')

# Quantity pattern
QTY_PATTERN = re.compile(r'\b(\d+)\s*(?:szt\.?|pcs\.?|x)\b', re.IGNORECASE)

# Size patterns
SIZE_PATTERNS = [
    re.compile(r'\b(XS|S|M|L|XL|XXL|XXXL|2XL|3XL|4XL)\b', re.IGNORECASE),
    re.compile(r'\b(\d{2,3})\b'),  # Numeric sizes like 38, 40, 42, 128, 140
    re.compile(r'\b(\d+-\d+)\b'),  # Range sizes like 92-98
]


def _clean_barcode(val) -> Optional[str]:
    """Extract and validate EAN code."""
    if val is None:
        return None
    s = str(val).strip()
    # Remove any non-digit characters
    s = re.sub(r'\D', '', s)
    # Validate length (EAN-8 or EAN-13)
    if len(s) in (8, 13):
        return s
    return None


def _to_decimal(val) -> Decimal:
    """Convert value to Decimal."""
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val
    s = str(val).strip().replace(',', '.').replace(' ', '')
    # Remove currency symbols
    s = re.sub(r'[^\d.]', '', s)
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def _to_int(val) -> int:
    """Convert value to integer."""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    s = re.sub(r'\D', '', s)
    try:
        return int(s)
    except ValueError:
        return 0


def _preprocess_image(image: "Image.Image") -> "Image.Image":
    """Preprocess image for better OCR results."""
    if not PILLOW_AVAILABLE:
        return image
    
    # Convert to grayscale
    if image.mode != 'L':
        image = image.convert('L')
    
    # Increase contrast
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(2.0)
    
    # Sharpen
    image = image.filter(ImageFilter.SHARPEN)
    
    # Binarize (threshold)
    threshold = 128
    image = image.point(lambda x: 255 if x > threshold else 0, mode='1')
    
    return image


def _extract_text_from_pdf_ocr(pdf_data: bytes, dpi: int = 300) -> str:
    """Extract text from PDF using OCR (for scanned documents)."""
    if not PDF2IMAGE_AVAILABLE or not TESSERACT_AVAILABLE:
        logger.warning("OCR dependencies not available")
        return ""
    
    try:
        # Convert PDF to images
        images = pdf2image.convert_from_bytes(pdf_data, dpi=dpi)
        
        full_text = []
        for i, img in enumerate(images):
            # Preprocess image
            if PILLOW_AVAILABLE:
                img = _preprocess_image(img)
            
            # OCR with Polish language
            # Use --psm 6 for uniform block of text
            custom_config = r'--oem 3 --psm 6 -l pol+eng'
            text = pytesseract.image_to_string(img, config=custom_config)
            full_text.append(text)
            logger.debug(f"OCR page {i+1}: {len(text)} characters")
        
        return '\n'.join(full_text)
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        return ""


def _extract_text_from_pdf_native(pdf_data: bytes) -> Tuple[str, bool]:
    """Extract text from PDF using pypdf.
    
    Returns:
        Tuple of (text, is_text_based) - is_text_based indicates if PDF has embedded text
    """
    try:
        reader = PdfReader(io.BytesIO(pdf_data))
        texts = []
        has_text = False
        
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                has_text = True
            texts.append(text)
        
        return '\n'.join(texts), has_text
    except Exception as e:
        logger.error(f"Native PDF extraction failed: {e}")
        return "", False


def _extract_invoice_number(text: str) -> Optional[str]:
    """Extract invoice number from text."""
    patterns = [
        r'[Ff]aktura\s*(?:[Vv][Aa][Tt])?\s*(?:nr\.?|numer)?\s*[:#]?\s*([A-Z0-9/\-]+)',
        r'[Nn]r\s+faktury[:\s]+([A-Z0-9/\-]+)',
        r'[Ff][Vv]\s*[:#]?\s*([A-Z0-9/\-]+)',
        r'[Dd]okument\s*[:#]?\s*([A-Z0-9/\-]+)',
        r'[Pp]aragon\s*(?:nr\.?)?\s*[:#]?\s*(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _extract_supplier(text: str) -> Optional[str]:
    """Extract supplier name from invoice."""
    patterns = [
        r'[Ss]przedawca[:\s]+([^\n]+)',
        r'[Ww]ystawca[:\s]+([^\n]+)',
        r'[Dd]ostawca[:\s]+([^\n]+)',
        r'[Ff]irma[:\s]+([^\n]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            supplier = match.group(1).strip()
            # Clean up - remove NIP, address etc
            supplier = re.sub(r'NIP[:\s]+\d+', '', supplier).strip()
            if supplier:
                return supplier
    return None


def _extract_invoice_date(text: str) -> Optional[str]:
    """Extract invoice date from text."""
    patterns = [
        r'[Dd]ata\s+(?:wystawienia|sprzedaży)?[:\s]+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})',
        r'(\d{1,2}[./-]\d{1,2}[./-]\d{4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            date_str = match.group(1)
            # Try to parse and normalize
            for fmt in ['%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d']:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime('%Y-%m-%d')
                except ValueError:
                    continue
            return date_str
    return None


def _find_ean_in_line(line: str) -> Optional[str]:
    """Find EAN code in a line of text."""
    match = EAN_PATTERN.search(line)
    if match:
        ean = match.group(1)
        # Validate checksum for EAN-13
        if len(ean) == 13:
            return ean if _validate_ean13(ean) else None
        return ean
    return None


def _validate_ean13(ean: str) -> bool:
    """Validate EAN-13 checksum."""
    if len(ean) != 13 or not ean.isdigit():
        return False
    
    total = 0
    for i, digit in enumerate(ean[:12]):
        weight = 1 if i % 2 == 0 else 3
        total += int(digit) * weight
    
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(ean[12])


def _find_price_in_line(line: str) -> Optional[Decimal]:
    """Find price in a line of text."""
    # Look for price-like patterns
    matches = PRICE_PATTERN.findall(line)
    if matches:
        # Usually the last price-like number is the unit price
        for zlotych, groszy in reversed(matches):
            try:
                price = Decimal(f"{zlotych}.{groszy}")
                # Reasonable price range
                if Decimal("1.00") <= price <= Decimal("9999.99"):
                    return price
            except InvalidOperation:
                continue
    return None


def _find_quantity_in_line(line: str) -> Optional[int]:
    """Find quantity in a line of text."""
    match = QTY_PATTERN.search(line)
    if match:
        return _to_int(match.group(1))
    
    # Fallback: look for standalone numbers at start
    numbers = re.findall(r'^\s*(\d+)\s', line)
    if numbers:
        qty = int(numbers[0])
        if 1 <= qty <= 1000:
            return qty
    return None


def _find_size_in_line(line: str) -> Optional[str]:
    """Find size in a line of text."""
    for pattern in SIZE_PATTERNS:
        match = pattern.search(line)
        if match:
            return match.group(1).upper()
    return None


def _parse_table_lines(lines: List[str]) -> List[InvoiceItem]:
    """Parse invoice table lines into items."""
    items = []
    
    # Group related lines (item might span multiple lines)
    current_item = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Check if this looks like a new item line
        ean = _find_ean_in_line(line)
        price = _find_price_in_line(line)
        qty = _find_quantity_in_line(line)
        size = _find_size_in_line(line)
        
        # If we have at least 2 of: EAN, price, quantity - it's likely an item
        found_count = sum([bool(ean), bool(price), bool(qty)])
        
        if found_count >= 2 or ean:
            # Try to extract product name (usually at the start)
            name_match = re.match(r'^([\w\s\-]+?)(?:\s+\d|\s+[XSML]|\s+EAN)', line, re.IGNORECASE)
            name = name_match.group(1).strip() if name_match else ""
            
            item = InvoiceItem(
                name=name,
                color="",
                size=size or "",
                quantity=qty or 1,
                price=price or Decimal("0.00"),
                barcode=ean,
                raw_text=line,
            )
            items.append(item)
    
    return items


def _parse_tiptop_format(text: str) -> List[InvoiceItem]:
    """Parse Tip-Top invoice format."""
    items = []
    lines = text.splitlines()
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Tip-Top format: line starts with number + name
        m = re.match(r'(\d{1,2})([A-Za-z].*)', line)
        if not m:
            i += 1
            continue
        
        name = m.group(2).strip()
        
        # Next line has quantity and price info
        if i + 1 >= len(lines):
            break
        
        info = lines[i + 1].strip()
        
        # Extract quantity and price from info line
        qty_match = re.search(r'(\d+(?:[.,]\d+)?)\s*szt', info, re.IGNORECASE)
        qty = _to_int(qty_match.group(1)) if qty_match else 1
        
        # Price is usually the 4th number
        numbers = re.findall(r'(\d+[.,]\d{2})', info)
        price = _to_decimal(numbers[3]) if len(numbers) > 3 else Decimal("0.00")
        
        # Color might be before numbers
        color_match = re.match(r'^([A-Za-z\s]+?)\s*\d', info)
        color = color_match.group(1).strip().split()[-1] if color_match else ""
        
        # Size and barcode on line 3
        size = ""
        barcode = None
        if i + 2 < len(lines):
            line3 = lines[i + 2]
            size_match = re.search(r'Wariant:\s*([A-Za-z0-9]+)', line3)
            if size_match:
                size = size_match.group(1)
            bc_match = re.search(r'Kod kreskowy:\s*(\d+)', line3)
            if bc_match:
                barcode = _clean_barcode(bc_match.group(1))
        
        item = InvoiceItem(
            name=name,
            color=color,
            size=size,
            quantity=qty,
            price=price,
            barcode=barcode,
            raw_text='\n'.join(lines[i:i+4]),
        )
        items.append(item)
        
        i += 4 if i + 3 < len(lines) else i + 1
    
    return items


def parse_invoice_pdf(pdf_data: bytes) -> ParsedInvoice:
    """Parse PDF invoice and extract items.
    
    Uses multiple strategies:
    1. Try native PDF text extraction
    2. If text is sparse, use OCR
    3. Detect format and parse accordingly
    """
    # First try native extraction
    text, has_text = _extract_text_from_pdf_native(pdf_data)
    
    # If PDF has little text, try OCR
    if not has_text or len(text.strip()) < 100:
        logger.info("PDF appears to be scanned, attempting OCR")
        ocr_text = _extract_text_from_pdf_ocr(pdf_data)
        if ocr_text:
            text = ocr_text
    
    if not text.strip():
        logger.warning("Could not extract text from PDF")
        return ParsedInvoice(items=[], raw_text="")
    
    # Extract invoice metadata
    invoice_number = _extract_invoice_number(text)
    invoice_date = _extract_invoice_date(text)
    supplier = _extract_supplier(text)
    
    # Detect format and parse items
    if "Kod kreskowy" in text or "Wariant:" in text:
        # Tip-Top format
        items = _parse_tiptop_format(text)
    else:
        # Generic table format
        items = _parse_table_lines(text.splitlines())
    
    return ParsedInvoice(
        items=items,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        supplier=supplier,
        raw_text=text,
    )


def parse_invoice_excel(excel_data: bytes) -> ParsedInvoice:
    """Parse Excel invoice file."""
    df = pd.read_excel(io.BytesIO(excel_data))
    
    items = []
    for _, row in df.iterrows():
        item = InvoiceItem(
            name=str(row.get('Nazwa', row.get('Name', ''))).strip(),
            color=str(row.get('Kolor', row.get('Color', ''))).strip(),
            size=str(row.get('Rozmiar', row.get('Size', ''))).strip(),
            quantity=_to_int(row.get('Ilość', row.get('Quantity', row.get('Qty', 1)))),
            price=_to_decimal(row.get('Cena', row.get('Price', 0))),
            barcode=_clean_barcode(row.get('Barcode', row.get('EAN', row.get('Kod', None)))),
        )
        items.append(item)
    
    return ParsedInvoice(items=items)


def parse_invoice(file_data: bytes, filename: str) -> ParsedInvoice:
    """Parse invoice file (auto-detect format)."""
    ext = filename.rsplit('.', 1)[-1].lower()
    
    if ext == 'pdf':
        return parse_invoice_pdf(file_data)
    elif ext in ('xlsx', 'xls'):
        return parse_invoice_excel(file_data)
    else:
        raise ValueError(f"Unsupported file format: {ext}")


def match_items_to_products(items: List[InvoiceItem], db_session) -> List[Dict]:
    """Match parsed items to database products by EAN.
    
    Returns list of dicts with matched product info.
    """
    from ..models import Product, ProductSize
    
    matched = []
    for item in items:
        match_result = {
            'item': item,
            'product': None,
            'product_size': None,
            'matched_by': None,
        }
        
        # Try to match by EAN first
        if item.barcode:
            ps = db_session.query(ProductSize).filter_by(barcode=item.barcode).first()
            if ps:
                match_result['product_size'] = ps
                match_result['product'] = ps.product
                match_result['matched_by'] = 'ean'
                matched.append(match_result)
                continue
        
        # Try to match by name + color
        if item.name:
            product = (
                db_session.query(Product)
                .filter(Product.name.ilike(f"%{item.name}%"))
                .first()
            )
            if product:
                match_result['product'] = product
                # Try to find matching size
                if item.size:
                    for ps in product.sizes:
                        if ps.size.upper() == item.size.upper():
                            match_result['product_size'] = ps
                            break
                match_result['matched_by'] = 'name'
        
        matched.append(match_result)
    
    return matched
