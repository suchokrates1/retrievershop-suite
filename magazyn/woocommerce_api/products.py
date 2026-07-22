"""Operacje na produktach WooCommerce."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .client import WooClient, WooClientError
from .media import (
    get_product_image_ids,
    upload_product_image_from_url,
)

logger = logging.getLogger(__name__)


def find_product_by_ean(client: WooClient, ean: str) -> Optional[dict]:
    """Szukaj produktu/wariantu po SKU (= EAN)."""
    if not ean:
        return None
    results = client.get("wp-json/wc/v3/products", params={"sku": ean, "per_page": 5}) or []
    if results:
        return results[0]
    # Warianty nie zawsze w glownym liscie — szukaj przez search
    results = client.get(
        "wp-json/wc/v3/products",
        params={"search": ean, "per_page": 20},
    ) or []
    for product in results:
        if product.get("sku") == ean:
            return product
        for variation_id in product.get("variations") or []:
            variation = client.get(f"wp-json/wc/v3/products/{product['id']}/variations/{variation_id}")
            if variation and variation.get("sku") == ean:
                return {**product, "_matched_variation": variation}
    return None


def create_or_update_variable_product(
    client: WooClient,
    *,
    woo_product_id: Optional[int],
    name: str,
    description_html: str,
    image_ids: Optional[list[int]] = None,
    image_urls: Optional[list[str]] = None,
    attributes: list[dict],
    category_ids: Optional[list[int]] = None,
    status: str = "publish",
    short_description: Optional[str] = None,
) -> dict:
    payload: dict[str, Any] = {
        "name": name,
        "type": "variable",
        "status": status,
        "attributes": attributes,
    }
    # Nie nadpisuj istniejacego opisu pustym stringiem
    if description_html and description_html.strip():
        payload["description"] = description_html
        if short_description is not None:
            payload["short_description"] = short_description
        else:
            # Fallback: plain cut bez zaleznosci od services.*
            plain = re.sub(r"<[^>]+>", " ", description_html)
            plain = re.sub(r"\s+", " ", plain).strip()
            payload["short_description"] = (plain[:159] + "…") if len(plain) > 160 else plain
    elif short_description:
        payload["short_description"] = short_description
    elif not woo_product_id:
        payload["description"] = ""
        payload["short_description"] = ""

    if category_ids:
        payload["categories"] = [{"id": int(cid)} for cid in category_ids if cid]
    images: list[dict[str, Any]] = []
    for image_id in image_ids or []:
        images.append({"id": image_id})
    for url in image_urls or []:
        if url:
            images.append({"src": url})
    if images:
        payload["images"] = images

    try:
        if woo_product_id:
            return client.put(f"wp-json/wc/v3/products/{woo_product_id}", json=payload)
        return client.post("wp-json/wc/v3/products", json=payload)
    except WooClientError as exc:
        if payload.get("images") and "image" in str(exc).lower():
            logger.warning("Woo product image rejected, retry without images: %s", exc)
            payload = {k: v for k, v in payload.items() if k != "images"}
            if woo_product_id:
                return client.put(f"wp-json/wc/v3/products/{woo_product_id}", json=payload)
            return client.post("wp-json/wc/v3/products", json=payload)
        raise


def upsert_variation(
    client: WooClient,
    product_id: int,
    *,
    variation_id: Optional[int],
    sku: str,
    regular_price: str,
    stock_quantity: int,
    size: str,
    color: Optional[str] = None,
    image_id: Optional[int] = None,
) -> dict:
    from .attributes import ensure_attribute

    attrs: list[dict[str, Any]] = []
    color_opt = (color or "").strip()
    if color_opt:
        color_id = ensure_attribute(client, "Kolor")
        if color_id:
            attrs.append({"id": int(color_id), "option": color_opt})
        else:
            attrs.append({"name": "Kolor", "option": color_opt})
    size_id = ensure_attribute(client, "Rozmiar")
    size_opt = (size or "").strip()
    if size_id:
        attrs.append({"id": int(size_id), "option": size_opt})
    else:
        attrs.append({"name": "Rozmiar", "option": size_opt})
    payload: dict[str, Any] = {
        "sku": sku,
        "regular_price": regular_price,
        "manage_stock": True,
        "stock_quantity": max(0, int(stock_quantity)),
        "attributes": attrs,
    }
    if image_id:
        payload["image"] = {"id": image_id}

    if variation_id:
        try:
            return client.put(
                f"wp-json/wc/v3/products/{product_id}/variations/{variation_id}",
                json=payload,
            )
        except WooClientError as exc:
            if exc.status_code != 404:
                raise
    try:
        return client.post(f"wp-json/wc/v3/products/{product_id}/variations", json=payload)
    except WooClientError as exc:
        # SKU juz zajete — zaktualizuj istniejacy wariant (ten sam parent)
        resource_id = None
        if isinstance(exc.payload, dict):
            resource_id = (exc.payload.get("data") or {}).get("resource_id")
        if resource_id and "product_invalid_sku" in str(exc):
            rid = int(resource_id)
            try:
                return client.put(
                    f"wp-json/wc/v3/products/{product_id}/variations/{rid}",
                    json=payload,
                )
            except WooClientError as put_exc:
                # resource_id moze byc na innym parentcie — wyczysc SKU i utworz nowy
                if put_exc.status_code in (400, 404):
                    try:
                        foreign = client.get(f"wp-json/wc/v3/products/{rid}")
                        foreign_parent = foreign.get("parent_id") or foreign.get("parent")
                        if foreign_parent:
                            client.put(
                                f"wp-json/wc/v3/products/{int(foreign_parent)}/variations/{rid}",
                                json={"sku": ""},
                            )
                    except WooClientError:
                        pass
                    return client.post(
                        f"wp-json/wc/v3/products/{product_id}/variations",
                        json=payload,
                    )
                raise
        raise
