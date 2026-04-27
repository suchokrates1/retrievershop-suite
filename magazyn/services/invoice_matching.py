"""Dopasowanie pozycji faktury do rozmiarow produktow."""

from __future__ import annotations

from typing import Callable, MutableMapping

from ..domain.inventory import get_product_sizes
from .product_matching import _fuzzy_match_product, _match_by_tiptop_sku


def match_invoice_rows(
    rows: list[MutableMapping],
    *,
    product_sizes_provider: Callable = get_product_sizes,
) -> tuple[list[MutableMapping], list]:
    """Dopasuj wiersze faktury po EAN, SKU TipTop, a na koncu fuzzy matchingiem."""
    product_sizes = product_sizes_provider()
    barcode_map = {product_size.barcode: product_size for product_size in product_sizes if product_size.barcode}

    for row in rows:
        _match_invoice_row(row, product_sizes, barcode_map)

    return rows, product_sizes


def _match_invoice_row(row: MutableMapping, product_sizes: list, barcode_map: dict) -> None:
    barcode = str(row.get("Barcode") or row.get("EAN") or "").strip()
    sku = str(row.get("SKU") or "").strip()

    row["matched_ps_id"] = None
    row["matched_name"] = None
    row["match_type"] = None

    if barcode and barcode in barcode_map:
        product_size = barcode_map[barcode]
        row["matched_ps_id"] = product_size.ps_id
        row["matched_name"] = f"{product_size.name} ({product_size.color}) {product_size.size}"
        row["match_type"] = "ean"
        return

    if sku:
        ps_id, match_name, match_type = _match_by_tiptop_sku(
            sku,
            product_sizes,
            row.get("Nazwa", ""),
        )
        if ps_id:
            row["matched_ps_id"] = ps_id
            row["matched_name"] = match_name
            row["match_type"] = match_type
            return

    ps_id, match_name, match_type = _fuzzy_match_product(
        row.get("Nazwa", ""),
        row.get("Kolor", ""),
        row.get("Rozmiar", ""),
        product_sizes,
    )
    if ps_id:
        row["matched_ps_id"] = ps_id
        row["matched_name"] = match_name
        row["match_type"] = match_type


__all__ = ["match_invoice_rows"]