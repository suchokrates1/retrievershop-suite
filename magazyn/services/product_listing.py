"""Przygotowanie danych listy produktow dla widoku magazynu."""

from __future__ import annotations

from typing import Callable, Dict, List, MutableMapping, Sequence

from ..domain.products import list_products

ALLOWED_PER_PAGE = {25, 50, 100, 200}
DEFAULT_PER_PAGE = 50


def filter_products(products: Sequence[MutableMapping], search: str) -> List[MutableMapping]:
    """Przefiltruj produkty po polach widocznych na liscie."""
    if not search:
        return list(products)

    normalized_search = search.lower()
    fields = ("category", "series", "color", "brand", "name")
    return [
        product
        for product in products
        if any(normalized_search in (product.get(field) or "").lower() for field in fields)
    ]


def build_items_context(
    *,
    search: str,
    page: int,
    per_page: int,
    products_provider: Callable[[], List[MutableMapping]] = list_products,
) -> Dict[str, object]:
    """Zbuduj kontekst szablonu listy produktow."""
    if per_page not in ALLOWED_PER_PAGE:
        per_page = DEFAULT_PER_PAGE

    products = filter_products(products_provider(), search)
    total = len(products)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), total_pages)

    start = (page - 1) * per_page
    paginated = products[start:start + per_page]

    return {
        "products": paginated,
        "search": search,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


__all__ = ["ALLOWED_PER_PAGE", "DEFAULT_PER_PAGE", "build_items_context", "filter_products"]