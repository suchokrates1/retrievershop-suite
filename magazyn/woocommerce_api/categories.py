"""Kategorie produktow WooCommerce (product_cat)."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

from .client import WooClient, WooClientError

logger = logging.getLogger(__name__)

# Nazwy magazynu → istniejące nazwy w WP (unikamy duplikatow)
CATEGORY_ALIASES: dict[str, str] = {
    "Szelki": "Szelki",
    "Smycz": "Smycze",
    "Pas bezpieczeństwa": "Pasy bezpieczeństwa",
    "Pasy bezpieczeństwa": "Pasy bezpieczeństwa",
    "Pas samochodowy": "Pasy bezpieczeństwa",
    "Pasy samochodowe": "Pasy bezpieczeństwa",
}

_category_cache: dict[str, int] = {}


def resolve_category_name(magazyn_category: str | None) -> str | None:
    """Zmapuj nazwe kategorii magazynu na nazwe w Woo."""
    if not magazyn_category:
        return None
    name = str(magazyn_category).strip()
    if not name:
        return None
    return CATEGORY_ALIASES.get(name, name)


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "kategoria"


def ensure_product_category(client: WooClient, magazyn_category: str | None) -> Optional[int]:
    """Znajdz lub utworz kategorie product_cat. Zwraca term ID albo None."""
    woo_name = resolve_category_name(magazyn_category)
    if not woo_name:
        return None

    cached = _category_cache.get(woo_name.lower())
    if cached:
        return cached

    slug = _slugify(woo_name)
    try:
        existing = client.get(
            "wp-json/wc/v3/products/categories",
            params={"search": woo_name, "per_page": 100},
        ) or []
    except WooClientError as exc:
        logger.warning("Woo categories search failed: %s", exc)
        existing = []

    for item in existing:
        if (item.get("name") or "").strip().lower() == woo_name.lower():
            cat_id = int(item["id"])
            _category_cache[woo_name.lower()] = cat_id
            return cat_id
        if (item.get("slug") or "") == slug:
            cat_id = int(item["id"])
            _category_cache[woo_name.lower()] = cat_id
            return cat_id

    try:
        created = client.post(
            "wp-json/wc/v3/products/categories",
            json={"name": woo_name, "slug": slug},
        )
        cat_id = int(created["id"])
        _category_cache[woo_name.lower()] = cat_id
        logger.info("Utworzono kategorie Woo %s id=%s", woo_name, cat_id)
        return cat_id
    except WooClientError as exc:
        # Rasa: kategoria juz istnieje (race) — sprobuj ponownie wyszukac
        logger.warning("Woo category create failed for %s: %s", woo_name, exc)
        try:
            existing = client.get(
                "wp-json/wc/v3/products/categories",
                params={"slug": slug, "per_page": 5},
            ) or []
            if existing:
                cat_id = int(existing[0]["id"])
                _category_cache[woo_name.lower()] = cat_id
                return cat_id
        except WooClientError:
            pass
        return None


def clear_category_cache() -> None:
    _category_cache.clear()


__all__ = [
    "CATEGORY_ALIASES",
    "clear_category_cache",
    "ensure_product_category",
    "resolve_category_name",
]
