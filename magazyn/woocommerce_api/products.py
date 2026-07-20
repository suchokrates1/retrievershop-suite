"""Operacje na produktach WooCommerce."""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from .client import WooClient, WooClientError

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


def upload_product_image_from_url(client: WooClient, image_url: str, filename: str) -> Optional[int]:
    """Pobierz obraz z URL i wgraj do WP Media Library. Zwraca attachment ID.

    Allegro CDN nie ma rozszerzenia pliku — wymuszamy ``.jpg`` i ``image/jpeg``.
    Auth: Application Password (``WP_APP_USER`` / ``WP_APP_PASSWORD``), bo
    klucze WooCommerce REST nie maja prawa do ``wp/v2/media``.
    """
    from ..settings_store import settings_store

    try:
        img = requests.get(
            image_url,
            timeout=45,
            headers={"User-Agent": "retrievershop-magazyn/woo-media"},
        )
        img.raise_for_status()
    except Exception as exc:
        logger.warning("Nie pobrano obrazu %s: %s", image_url, exc)
        return None

    if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        filename = f"{filename}.jpg"
    content_type = img.headers.get("Content-Type") or "image/jpeg"
    if "octet-stream" in content_type or not content_type.startswith("image/"):
        content_type = "image/jpeg"

    media_url = client.base_url + "wp-json/wp/v2/media"
    wp_user = settings_store.get("WP_APP_USER") or ""
    wp_pass = settings_store.get("WP_APP_PASSWORD") or ""
    auth = (wp_user, wp_pass) if wp_user and wp_pass else (client.consumer_key, client.consumer_secret)

    response = requests.post(
        media_url,
        auth=auth,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
        },
        data=img.content,
        timeout=60,
    )
    if response.status_code >= 400:
        logger.warning("Upload mediow WP failed %s: %s", response.status_code, response.text[:300])
        return None
    return response.json().get("id")


def create_or_update_variable_product(
    client: WooClient,
    *,
    woo_product_id: Optional[int],
    name: str,
    description_html: str,
    image_ids: Optional[list[int]] = None,
    image_urls: Optional[list[str]] = None,
    attributes: list[dict],
    status: str = "publish",
) -> dict:
    payload: dict[str, Any] = {
        "name": name,
        "type": "variable",
        "status": status,
        "description": description_html or "",
        "short_description": (description_html or "")[:400],
        "attributes": attributes,
    }
    images: list[dict[str, Any]] = []
    for image_id in image_ids or []:
        images.append({"id": image_id})
    # WC REST potrafi pobrac obraz z URL (nie wymaga WP Media auth)
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
        # Allegro CDN / MIME bywa odrzucane przez WP — zapisz produkt bez zdjec
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
    image_id: Optional[int] = None,
) -> dict:
    payload: dict[str, Any] = {
        "sku": sku,
        "regular_price": regular_price,
        "manage_stock": True,
        "stock_quantity": max(0, int(stock_quantity)),
        "attributes": [{"name": "Rozmiar", "option": size}],
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
    return client.post(f"wp-json/wc/v3/products/{product_id}/variations", json=payload)
