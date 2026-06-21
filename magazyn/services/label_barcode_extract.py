"""Ekstrakcja kodów kreskowych z etykiet PDF — tylko Automat DHL BOX 24/7."""

from __future__ import annotations

import io
import logging
import re

from pypdf import PdfReader

logger = logging.getLogger(__name__)

DHL_BOX_DELIVERY_MARKER = "automat dhl box"

# DHL license plate: (J) JD00 003 0230864 000435460935 → JJD000030230864000435460935
DHL_JJD_TEXT_RE = re.compile(r"\(J\)\s*J\s*D\s*([\d\s]+)", re.IGNORECASE)
# DHL routing: (2L) PL02495+83545000 → 2LPL02495+83545000
DHL_ROUTING_TEXT_RE = re.compile(r"\(2L\)\s*([A-Z0-9+]+)", re.IGNORECASE)
JJD_RAW_RE = re.compile(r"JJD\d{14,32}", re.IGNORECASE)
ROUTING_2L_RAW_RE = re.compile(r"2L[A-Z]{2}\d+\+[0-9]+", re.IGNORECASE)
DHL_WAYBILL_RE = re.compile(r"Nr przesylki:\s*(\d{11})", re.IGNORECASE)


def needs_dhl_box_label_barcode_extraction(delivery_method: str | None) -> bool:
    """Czy po pobraniu etykiety trzeba wyciągnąć kody JJD/routing z PDF."""
    if not delivery_method:
        return False
    return DHL_BOX_DELIVERY_MARKER in delivery_method.lower()


def _normalize_jjd_from_text(digits_with_spaces: str) -> str | None:
    digits = re.sub(r"\s+", "", digits_with_spaces.strip())
    if len(digits) < 14:
        return None
    return f"JJD{digits}"


def _normalize_routing_from_text(body: str) -> str | None:
    value = body.strip().upper()
    if not value:
        return None
    if value.startswith("2L"):
        return value
    return f"2L{value}"


def extract_dhl_box_barcodes_from_label_text(text: str) -> list[str]:
    """Wyciągnij kody z warstwy tekstowej etykiety DHL BOX (JJD + routing 2L)."""
    if not text:
        return []

    seen: list[str] = []

    def add(raw: str | None) -> None:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.append(value)

    for match in DHL_JJD_TEXT_RE.finditer(text):
        normalized = _normalize_jjd_from_text(match.group(1))
        if normalized:
            add(normalized)

    for match in DHL_ROUTING_TEXT_RE.finditer(text):
        normalized = _normalize_routing_from_text(match.group(1))
        if normalized:
            add(normalized)

    for match in JJD_RAW_RE.finditer(text):
        add(match.group(0).upper())

    for match in ROUTING_2L_RAW_RE.finditer(text):
        add(match.group(0).upper())

    for match in DHL_WAYBILL_RE.finditer(text):
        add(match.group(1))

    return seen


def extract_dhl_box_barcodes_from_label_pdf(label_bytes: bytes) -> list[str]:
    """Wyciągnij kody kreskowe z PDF etykiety Automat DHL BOX 24/7."""
    if not label_bytes:
        return []

    try:
        reader = PdfReader(io.BytesIO(label_bytes))
        text_parts = [page.extract_text() or "" for page in reader.pages]
        return extract_dhl_box_barcodes_from_label_text("\n".join(text_parts))
    except Exception as exc:
        logger.warning("Nie udało się odczytać kodów DHL z etykiety PDF: %s", exc)
        return []


# Zachowaj stare nazwy dla kompatybilności wewnętrznej skryptów ops.
extract_barcodes_from_label_text = extract_dhl_box_barcodes_from_label_text
extract_barcodes_from_label_pdf = extract_dhl_box_barcodes_from_label_pdf


__all__ = [
    "extract_barcodes_from_label_pdf",
    "extract_barcodes_from_label_text",
    "extract_dhl_box_barcodes_from_label_pdf",
    "extract_dhl_box_barcodes_from_label_text",
    "needs_dhl_box_label_barcode_extraction",
]
