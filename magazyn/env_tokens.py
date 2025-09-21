"""Utilities for keeping Allegro OAuth tokens in sync."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from typing import Optional


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

    # Import lazily to avoid circular imports with ``magazyn.app``.
    from .app import load_settings, write_env  # pylint: disable=import-outside-toplevel

    values: MutableMapping[str, str] = load_settings()
    if ***REMOVED*** is not None:
        values["ALLEGRO_ACCESS_TOKEN"] = ***REMOVED***
    if refresh_token is not None:
        values["ALLEGRO_REFRESH_TOKEN"] = refresh_token

    write_env(values)


def clear_allegro_tokens() -> None:
    """Remove Allegro OAuth tokens from the environment and persisted settings."""

    os.environ.pop("ALLEGRO_ACCESS_TOKEN", None)
    os.environ.pop("ALLEGRO_REFRESH_TOKEN", None)

    # Import lazily to avoid circular imports with ``magazyn.app``.
    from .app import load_settings, write_env  # pylint: disable=import-outside-toplevel

    values: MutableMapping[str, str] = load_settings()

    values.pop("ALLEGRO_ACCESS_TOKEN", None)
    values.pop("ALLEGRO_REFRESH_TOKEN", None)

    write_env(values)

