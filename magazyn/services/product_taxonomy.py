"""Distinct kategorie, marki i serie z bazy produktow."""

from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy import func

from ..db import get_session
from ..models.products import Product

NEW_TAXONOMY_VALUE = "__NEW__"


def _distinct_values(column) -> List[str]:
    with get_session() as db:
        rows = (
            db.query(column)
            .filter(column.isnot(None), func.trim(column) != "")
            .distinct()
            .order_by(column.asc())
            .all()
        )
    return [row[0].strip() for row in rows if row[0] and str(row[0]).strip()]


def distinct_categories() -> List[str]:
    return _distinct_values(Product.category)


def distinct_brands() -> List[str]:
    return _distinct_values(Product.brand)


def distinct_series() -> List[str]:
    return _distinct_values(Product.series)


def taxonomy_options(values: Iterable[str], current: Optional[str] = None) -> List[str]:
    """Posortowana lista wartosci z bazy, z aktualna wartoscia produktu jesli brakuje."""
    merged = {value.strip() for value in values if value and str(value).strip()}
    if current and str(current).strip():
        merged.add(str(current).strip())
    return sorted(merged, key=str.casefold)


def resolve_taxonomy_value(
    selected: Optional[str],
    custom: Optional[str],
    *,
    required: bool = True,
    field_label: str = "wartość",
) -> Optional[str]:
    """Rozwiaz wybor z listy lub nowa wartosc z pola tekstowego."""
    selected_value = (selected or "").strip()
    if selected_value == NEW_TAXONOMY_VALUE:
        resolved = (custom or "").strip()
        if not resolved:
            raise ValueError(f"Podaj nową {field_label}.")
        return resolved
    if not selected_value:
        if required:
            raise ValueError(f"Wybierz {field_label}.")
        return None
    return selected_value


def resolve_optional_series(selected: Optional[str], custom: Optional[str]) -> Optional[str]:
    """Seria moze byc pusta (-- Brak serii --)."""
    selected_value = (selected or "").strip()
    if selected_value == NEW_TAXONOMY_VALUE:
        return (custom or "").strip() or None
    return selected_value or None


def parse_product_form_taxonomy(form_data) -> tuple[str, str, Optional[str]]:
    """Rozwiaz kategorie, marke i serie z pol formularza add/edit item."""
    category = resolve_taxonomy_value(
        form_data.get("category"),
        form_data.get("custom_category"),
        field_label="kategorię",
    )
    brand = resolve_taxonomy_value(
        form_data.get("brand"),
        form_data.get("custom_brand"),
        required=False,
        field_label="markę",
    ) or "Truelove"
    series = resolve_optional_series(
        form_data.get("series"),
        form_data.get("custom_series"),
    )
    return category, brand, series


def edit_item_taxonomy_context(product: dict) -> dict:
    """Kontekst szablonu edit_item: listy taxonomy z bazy + aktualne wartosci."""
    return {
        "product_categories": taxonomy_options(
            distinct_categories(), product.get("category")
        ),
        "product_brands": taxonomy_options(distinct_brands(), product.get("brand")),
        "product_series": taxonomy_options(distinct_series(), product.get("series")),
        "new_taxonomy_value": NEW_TAXONOMY_VALUE,
    }


__all__ = [
    "NEW_TAXONOMY_VALUE",
    "distinct_brands",
    "distinct_categories",
    "distinct_series",
    "edit_item_taxonomy_context",
    "parse_product_form_taxonomy",
    "resolve_optional_series",
    "resolve_taxonomy_value",
    "taxonomy_options",
]
