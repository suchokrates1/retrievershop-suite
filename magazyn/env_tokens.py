"""Utilities for keeping Allegro OAuth tokens in sync."""

from __future__ import annotations

from typing import Optional

from .settings_store import settings_store


def update_allegro_tokens(
    access_token: Optional[str] = None, refresh_token: Optional[str] = None
) -> None:
    """Persist new Allegro OAuth tokens and update ``os.environ``.

    Parameters
    ----------
    access_token:
        The freshly obtained access token. If ``None`` the persisted value is not
        modified.
    refresh_token:
        The accompanying refresh token. If ``None`` the previous value is kept.
    """

    if access_token is None and refresh_token is None:
        return

    updates = {}
    if access_token is not None:
        updates["ALLEGRO_ACCESS_TOKEN"] = access_token
    if refresh_token is not None:
        updates["ALLEGRO_REFRESH_TOKEN"] = refresh_token
    if updates:
        settings_store.update(updates)


def clear_allegro_tokens() -> None:
    """Remove Allegro OAuth tokens from the environment and persisted settings."""

    settings_store.update(
        {
            "ALLEGRO_ACCESS_TOKEN": None,
            "ALLEGRO_REFRESH_TOKEN": None,
        }
    )

