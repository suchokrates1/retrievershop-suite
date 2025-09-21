"""Utilities for keeping Allegro OAuth tokens in sync."""

from __future__ import annotations

import os
from typing import Optional

from .settings_store import settings_store


def update_allegro_tokens(
    ***REMOVED***: ***REMOVED*** = None, refresh_token: ***REMOVED*** = None
) -> None:
    """Persist new Allegro OAuth tokens and update ``os.environ``.

    Parameters
    ----------
    ***REMOVED***:
        The freshly obtained access token. If ``None`` the persisted value is not
        modified.
    refresh_token:
        The accompanying refresh token. If ``None`` the previous value is kept.
    """

    if ***REMOVED*** is None and refresh_token is None:
        return

    if ***REMOVED*** is not None:
        os.environ["ALLEGRO_ACCESS_TOKEN"] = ***REMOVED***
    if refresh_token is not None:
        os.environ["ALLEGRO_REFRESH_TOKEN"] = refresh_token

    updates = {}
    if ***REMOVED*** is not None:
        updates["ALLEGRO_ACCESS_TOKEN"] = ***REMOVED***
    if refresh_token is not None:
        updates["ALLEGRO_REFRESH_TOKEN"] = refresh_token
    if updates:
        settings_store.update(updates)


def clear_allegro_tokens() -> None:
    """Remove Allegro OAuth tokens from the environment and persisted settings."""

    os.environ.pop("ALLEGRO_ACCESS_TOKEN", None)
    os.environ.pop("ALLEGRO_REFRESH_TOKEN", None)

    settings_store.update(
        {
            "ALLEGRO_ACCESS_TOKEN": None,
            "ALLEGRO_REFRESH_TOKEN": None,
        }
    )

