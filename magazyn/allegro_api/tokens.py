"""Wspólne operacje na tokenach Allegro API."""

from __future__ import annotations

import logging

from .auth import refresh_token as _refresh_oauth_token
from ..env_tokens import update_allegro_tokens
from ..settings_store import SettingsPersistenceError, settings_store


logger = logging.getLogger(__name__)


def get_allegro_token() -> tuple[str, str]:
    """Pobierz aktualny token Allegro z settings_store."""
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")
    if not token:
        raise RuntimeError("Brak tokenu Allegro - wymagana autoryzacja")
    return token, refresh


def refresh_allegro_token(current_refresh: str) -> str:
    """Odśwież token Allegro i zwróć nowy access token."""
    try:
        token_data = _refresh_oauth_token(current_refresh)
    except Exception as exc:
        raise RuntimeError(
            "Nie udalo sie odswiezyc tokenu Allegro - wymagana ponowna autoryzacja"
        ) from exc

    new_token = token_data.get("access_token")
    if not new_token:
        raise RuntimeError("Brak tokenu po odswiezeniu - wymagana ponowna autoryzacja")

    new_refresh = token_data.get("refresh_token") or current_refresh
    expires_in = token_data.get("expires_in")
    try:
        update_allegro_tokens(new_token, new_refresh, expires_in)
    except SettingsPersistenceError:
        logger.warning("Nie udalo sie zapisac odswiezonego tokenu do settings_store")

    return new_token


__all__ = ["get_allegro_token", "refresh_allegro_token"]