"""Globalne atrybuty produktow WooCommerce (Marka, Seria, Kolor, Rozmiar)."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Optional

from .client import WooClient, WooClientError

logger = logging.getLogger(__name__)

_attribute_cache: dict[str, int] = {}
_term_cache: dict[tuple[int, str], int] = {}


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "attr"


def clear_attribute_cache() -> None:
    _attribute_cache.clear()
    _term_cache.clear()


def ensure_attribute(
    client: WooClient,
    name: str,
    *,
    attr_type: str = "select",
    has_archives: bool = True,
) -> Optional[int]:
    """Znajdz lub utworz globalny atrybut produktu. Zwraca attribute ID."""
    name = (name or "").strip()
    if not name:
        return None

    cached = _attribute_cache.get(name.lower())
    if cached:
        return cached

    try:
        existing = client.get("wp-json/wc/v3/products/attributes", params={"per_page": 100}) or []
    except WooClientError as exc:
        logger.warning("Woo attributes list failed: %s", exc)
        return None

    for item in existing:
        if (item.get("name") or "").strip().lower() == name.lower():
            attr_id = int(item["id"])
            _attribute_cache[name.lower()] = attr_id
            return attr_id

    try:
        created = client.post(
            "wp-json/wc/v3/products/attributes",
            json={
                "name": name,
                "slug": f"pa_{_slugify(name)}",
                "type": attr_type,
                "order_by": "menu_order",
                "has_archives": has_archives,
            },
        )
        attr_id = int(created["id"])
        _attribute_cache[name.lower()] = attr_id
        logger.info("Utworzono atrybut Woo %s id=%s", name, attr_id)
        return attr_id
    except WooClientError as exc:
        logger.warning("Woo attribute create failed for %s: %s", name, exc)
        # Refresh list in case of race / already exists
        try:
            existing = client.get("wp-json/wc/v3/products/attributes", params={"per_page": 100}) or []
            for item in existing:
                if (item.get("name") or "").strip().lower() == name.lower():
                    attr_id = int(item["id"])
                    _attribute_cache[name.lower()] = attr_id
                    return attr_id
        except WooClientError:
            pass
        return None


def ensure_attribute_term(client: WooClient, attribute_id: int, term_name: str) -> Optional[int]:
    """Znajdz lub utworz term atrybutu. Zwraca term ID."""
    term_name = (term_name or "").strip()
    if not term_name or not attribute_id:
        return None

    cache_key = (int(attribute_id), term_name.lower())
    cached = _term_cache.get(cache_key)
    if cached:
        return cached

    path = f"wp-json/wc/v3/products/attributes/{attribute_id}/terms"
    try:
        existing = client.get(path, params={"search": term_name, "per_page": 100}) or []
    except WooClientError as exc:
        logger.warning("Woo attribute terms search failed attr=%s: %s", attribute_id, exc)
        existing = []

    for item in existing:
        if (item.get("name") or "").strip().lower() == term_name.lower():
            term_id = int(item["id"])
            _term_cache[cache_key] = term_id
            return term_id

    try:
        created = client.post(path, json={"name": term_name})
        term_id = int(created["id"])
        _term_cache[cache_key] = term_id
        return term_id
    except WooClientError as exc:
        logger.warning(
            "Woo attribute term create failed attr=%s term=%s: %s",
            attribute_id,
            term_name,
            exc,
        )
        try:
            existing = client.get(path, params={"search": term_name, "per_page": 100}) or []
            for item in existing:
                if (item.get("name") or "").strip().lower() == term_name.lower():
                    term_id = int(item["id"])
                    _term_cache[cache_key] = term_id
                    return term_id
        except WooClientError:
            pass
        return None


def build_product_attributes(
    client: WooClient,
    *,
    brand: str | None,
    series: str | None,
    color: str | None,
    size_options: list[str],
) -> list[dict[str, Any]]:
    """Zbuduj liste atrybutow payloadu produktu variable (globalne ID gdy dostepne)."""
    attributes: list[dict[str, Any]] = []

    def _add_fixed(name: str, value: str | None, *, variation: bool = False) -> None:
        value = (value or "").strip()
        if not value:
            return
        attr_id = ensure_attribute(client, name)
        if attr_id:
            ensure_attribute_term(client, attr_id, value)
            attributes.append(
                {
                    "id": attr_id,
                    "visible": True,
                    "variation": variation,
                    "options": [value],
                }
            )
        else:
            attributes.append(
                {
                    "name": name,
                    "visible": True,
                    "variation": variation,
                    "options": [value],
                }
            )

    _add_fixed("Marka", brand)
    _add_fixed("Seria", series)
    _add_fixed("Kolor", color)

    sizes = [s.strip() for s in size_options if s and str(s).strip()]
    if sizes:
        attr_id = ensure_attribute(client, "Rozmiar")
        if attr_id:
            for size in sizes:
                ensure_attribute_term(client, attr_id, size)
            attributes.append(
                {
                    "id": attr_id,
                    "visible": True,
                    "variation": True,
                    "options": sizes,
                }
            )
        else:
            attributes.append(
                {
                    "name": "Rozmiar",
                    "visible": True,
                    "variation": True,
                    "options": sizes,
                }
            )

    return attributes


__all__ = [
    "build_product_attributes",
    "clear_attribute_cache",
    "ensure_attribute",
    "ensure_attribute_term",
]
