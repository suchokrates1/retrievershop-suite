"""Dostep do danych potrzebnych scraperowi cen Allegro."""

from __future__ import annotations

import logging

from .parser import normalize_seller_name

logger = logging.getLogger(__name__)

_excluded_sellers_cache: set[str] = set()
_excluded_sellers_loaded = False


def ensure_runtime_db_configured() -> bool:
    """Zapewnia skonfigurowany engine DB dla uruchomien standalone."""
    try:
        from magazyn.db import SessionLocal, configure_engine

        if SessionLocal is not None:
            return True

        from magazyn.config import settings

        configure_engine(settings.DB_PATH)
        return True
    except Exception as exc:
        logger.warning("Nie udalo sie skonfigurowac bazy danych: %s", exc)
        return False


def get_excluded_sellers() -> set[str]:
    """Pobiera liste wykluczonych sprzedawcow z bazy danych."""
    global _excluded_sellers_cache, _excluded_sellers_loaded

    if _excluded_sellers_loaded:
        return _excluded_sellers_cache

    try:
        ensure_runtime_db_configured()
        from magazyn.db import get_session
        from magazyn.models.price_reports import ExcludedSeller

        with get_session() as session:
            excluded = session.query(ExcludedSeller.seller_name).all()
            _excluded_sellers_cache = {
                normalized
                for entry in excluded
                if (normalized := normalize_seller_name(entry.seller_name))
            }
            _excluded_sellers_loaded = True
            if _excluded_sellers_cache:
                logger.info("Zaladowano %s wykluczonych sprzedawcow", len(_excluded_sellers_cache))
    except Exception as exc:
        logger.warning("Nie udalo sie pobrac wykluczonych sprzedawcow: %s", exc)
        _excluded_sellers_cache = set()
        _excluded_sellers_loaded = True

    return _excluded_sellers_cache


def reload_excluded_sellers() -> set[str]:
    """Wymusza ponowne zaladowanie listy wykluczonych sprzedawcow."""
    global _excluded_sellers_loaded
    _excluded_sellers_loaded = False
    return get_excluded_sellers()