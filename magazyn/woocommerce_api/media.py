"""WP Media Library — upload zdjęć (Application Password)."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from .client import WooClient, WooClientError

logger = logging.getLogger(__name__)


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


__all__ = [
    "find_media_id_by_filename",
    "get_product_image_ids",
    "upload_product_image_from_url",
]
