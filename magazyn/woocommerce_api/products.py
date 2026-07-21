"""Operacje na produktach WooCommerce."""

from __future__ import annotations

import logging
import re
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


def _wp_media_auth(client: WooClient):
    from ..settings_store import settings_store

    wp_user = settings_store.get("WP_APP_USER") or ""
    wp_pass = settings_store.get("WP_APP_PASSWORD") or ""
    if wp_user and wp_pass:
        return (wp_user, wp_pass)
    return (client.consumer_key, client.consumer_secret)


def find_media_id_by_filename(client: WooClient, filename: str) -> Optional[int]:
    """Szukaj istniejacego attachmentu WP po nazwie pliku (idempotencja syncu)."""
    if not filename:
        return None
    media_url = client.base_url + "wp-json/wp/v2/media"
    try:
        response = requests.get(
            media_url,
            auth=_wp_media_auth(client),
            params={"search": filename, "per_page": 20},
            timeout=30,
        )
        if response.status_code >= 400:
            return None
        for item in response.json() or []:
            source = (item.get("source_url") or "").rsplit("/", 1)[-1]
            slug = item.get("slug") or ""
            title = ((item.get("title") or {}).get("rendered") or "")
            if filename in {source, f"{slug}.jpg", title, f"{title}.jpg"}:
                return int(item["id"])
            if filename.rsplit(".", 1)[0] == slug:
                return int(item["id"])
    except Exception as exc:
        logger.debug("Media search failed for %s: %s", filename, exc)
    return None


def get_product_image_ids(client: WooClient, woo_product_id: int) -> list[int]:
    """Zwraca ID zdjec juz podpietych do produktu Woo."""
    try:
        product = client.get(f"wp-json/wc/v3/products/{woo_product_id}")
    except WooClientError:
        return []
    ids: list[int] = []
    for image in product.get("images") or []:
        image_id = image.get("id")
        if image_id:
            ids.append(int(image_id))
    return ids


def upload_product_image_from_url(
    client: WooClient,
    image_url: str,
    filename: str,
    *,
    alt_text: str = "",
) -> Optional[int]:
    """Pobierz obraz z URL i wgraj do WP Media Library. Zwraca attachment ID.

    Allegro CDN nie ma rozszerzenia pliku — wymuszamy ``.jpg`` i ``image/jpeg``.
    Auth: Application Password (``WP_APP_USER`` / ``WP_APP_PASSWORD``), bo
    klucze WooCommerce REST nie maja prawa do ``wp/v2/media``.
    """
    if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        filename = f"{filename}.jpg"

    existing_id = find_media_id_by_filename(client, filename)
    if existing_id:
        if alt_text:
            _set_media_alt(client, int(existing_id), alt_text)
        return existing_id

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

    content_type = img.headers.get("Content-Type") or "image/jpeg"
    if "octet-stream" in content_type or not content_type.startswith("image/"):
        content_type = "image/jpeg"

    media_url = client.base_url + "wp-json/wp/v2/media"
    response = requests.post(
        media_url,
        auth=_wp_media_auth(client),
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
    media_id = response.json().get("id")
    if media_id and alt_text:
        _set_media_alt(client, int(media_id), alt_text)
    return media_id


def _set_media_alt(client: WooClient, media_id: int, alt_text: str) -> None:
    try:
        requests.post(
            client.base_url + f"wp-json/wp/v2/media/{media_id}",
            auth=_wp_media_auth(client),
            json={"alt_text": alt_text},
            timeout=30,
        )
    except Exception as exc:
        logger.debug("Nie ustawiono alt dla media %s: %s", media_id, exc)


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
    attrs: list[dict[str, str]] = []
    color_opt = (color or "").strip()
    if color_opt:
        attrs.append({"name": "Kolor", "option": color_opt})
    attrs.append({"name": "Rozmiar", "option": size})
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
        # SKU juz zajete przez istniejacy wariant — zaktualizuj go
        resource_id = None
        if isinstance(exc.payload, dict):
            resource_id = (exc.payload.get("data") or {}).get("resource_id")
        if resource_id and "product_invalid_sku" in str(exc):
            return client.put(
                f"wp-json/wc/v3/products/{product_id}/variations/{int(resource_id)}",
                json=payload,
            )
        raise
