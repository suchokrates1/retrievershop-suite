from datetime import datetime, timezone
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping
from urllib.parse import urlparse, parse_qs

import requests
from requests.exceptions import HTTPError
from sqlalchemy import or_

from .db import get_session, configure_engine
from .settings_store import SettingsPersistenceError, settings_store
from .config import settings

logger = logging.getLogger(__name__)


_COLOR_COMPONENT_PATTERN = re.compile(r"[\\s/\\-]+")


def _normalize_color_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    return stripped.casefold().strip()


def _normalized_product_color_components(value: str) -> set[str]:
    components: set[str] = set()
    for component in _COLOR_COMPONENT_PATTERN.split(value or ""):
        component = component.strip()
        if not component:
            continue
        normalized_component = normalize_color(component)
        key = _normalize_color_key(normalized_component)
        if key:
            components.add(key)
    return components


def _raise_settings_store_read_only(exc: SettingsPersistenceError) -> None:
    guidance = (
        "Cannot modify Allegro credentials because the settings store is read-only. "
        "Update them manually in the configuration file and rerun the synchronisation."
    )
    ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="settings_store").inc()
    logger.error(guidance, exc_info=True)
    raise RuntimeError(guidance) from exc


def _clear_cached_tokens():
    try:
        clear_allegro_tokens()
    except SettingsPersistenceError as exc:
        _raise_settings_store_read_only(exc)


def sync_offers():
    print("sync_offers called")
    return {}


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_from_href(href):
    try:
        query = parse_qs(urlparse(href).query)
    except Exception:
        return None, None
    offset = None
    limit = None
    offset_values = query.get("offset")
    if offset_values:
        offset = _parse_int(offset_values[0])
    limit_values = query.get("limit")
    if limit_values:
        limit = _parse_int(limit_values[0])
    return offset, limit


def _extract_pagination(next_data, current_limit):
    next_offset = None
    next_limit = current_limit

    if isinstance(next_data, Mapping):
        next_offset = _parse_int(next_data.get("offset"))
        new_limit = _parse_int(next_data.get("limit"))
        if new_limit is not None:
            next_limit = new_limit
        href = next_data.get("href")
        if href:
            href_offset, href_limit = _extract_from_href(href)
            if href_limit is not None:
                next_limit = href_limit
            if next_offset is None:
                next_offset = href_offset
    elif isinstance(next_data, str):
        href_offset, href_limit = _extract_from_href(next_data)
        if href_limit is not None:
            next_limit = href_limit
        next_offset = href_offset

    return next_offset, next_limit


if __name__ == "__main__":
    print("Starting allegro_sync")
    logging.basicConfig(level=logging.INFO)
    try:
        print("Reloading settings_store...")
        settings_store.reload()
        print("Reload successful")
    except Exception as e:
        print(f"Error in reload: {e}")
        raise
    try:
        print(f"DB_PATH: {settings.DB_PATH}")
        print("Configuring engine...")
        configure_engine(settings.DB_PATH)
        print("Engine configured, starting sync...")
    except Exception as e:
        print(f"Error during setup: {e}")
        raise
    sync_offers()

