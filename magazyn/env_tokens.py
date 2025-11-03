"""Utilities for keeping Allegro OAuth tokens in sync."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

from .settings_store import settings_store

LOGGER = logging.getLogger(__name__)


def update_allegro_tokens(
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    expires_in: Optional[int] = None,
    metadata: Optional[Mapping[str, object]] = None,
) -> None:
    """Persist new Allegro OAuth tokens and update ``os.environ``.

    Parameters
    ----------
    access_token:
        The freshly obtained access token. If ``None`` the persisted value is not
        modified.
    refresh_token:
        The accompanying refresh token. If ``None`` the previous value is kept.
    expires_in:
        Lifetime of the access token in seconds. When provided the value is
        stored alongside the tokens for later reference. The timestamp when the
        token expires is derived from this value and stored in
        ``ALLEGRO_TOKEN_METADATA``.
    metadata:
        Optional mapping with additional metadata values that should be stored
        alongside the tokens. When present these values are merged with any
        existing metadata.
    """

    if (
        access_token is None
        and refresh_token is None
        and expires_in is None
        and metadata is None
    ):
        return

    updates = {}
    if access_token is not None:
        updates["ALLEGRO_ACCESS_TOKEN"] = access_token
    if refresh_token is not None:
        updates["ALLEGRO_REFRESH_TOKEN"] = refresh_token
    expires_value: Optional[int] = None
    if expires_in is not None:
        try:
            expires_value = int(expires_in)
        except (TypeError, ValueError):
            expires_value = None
        updates["ALLEGRO_TOKEN_EXPIRES_IN"] = expires_in

    metadata_payload: dict[str, object] = {}
    existing_metadata_raw = settings_store.get("ALLEGRO_TOKEN_METADATA")
    if existing_metadata_raw:
        try:
            existing_metadata = json.loads(existing_metadata_raw)
            if isinstance(existing_metadata, dict):
                metadata_payload.update(existing_metadata)
        except (TypeError, ValueError):
            LOGGER.debug("Ignoring malformed Allegro token metadata", exc_info=True)

    now = datetime.now(timezone.utc)
    tokens_modified = (
        access_token is not None
        or refresh_token is not None
        or expires_in is not None
    )
    if tokens_modified:
        metadata_payload["obtained_at"] = now.isoformat()

    if expires_value is not None:
        metadata_payload["expires_in"] = expires_value
        expires_at_dt = now + timedelta(seconds=expires_value)
        metadata_payload["expires_at"] = expires_at_dt.isoformat()
        updates["ALLEGRO_TOKEN_EXPIRES_AT"] = int(expires_at_dt.timestamp())

    if metadata:
        metadata_payload.update(metadata)

    if metadata_payload:
        updates["ALLEGRO_TOKEN_METADATA"] = json.dumps(
            metadata_payload, ensure_ascii=False
        )

    if updates:
        settings_store.update(updates)


def clear_allegro_tokens() -> None:
    """Remove Allegro OAuth tokens from the environment and persisted settings."""

    settings_store.update(
        {
            "ALLEGRO_ACCESS_TOKEN": None,
            "ALLEGRO_REFRESH_TOKEN": None,
            "ALLEGRO_TOKEN_EXPIRES_IN": None,
            "ALLEGRO_TOKEN_METADATA": None,
        }
    )

