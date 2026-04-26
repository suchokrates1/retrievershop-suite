"""Prezentacyjne helpery widokow zamowien."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..status_config import get_status_display


def _unix_to_datetime(timestamp: Optional[int]) -> Optional[datetime]:
    """Convert Unix timestamp to datetime."""
    if timestamp:
        try:
            return datetime.fromtimestamp(timestamp)
        except (ValueError, OSError):
            pass
    return None


def _get_status_display(status: str) -> tuple[str, str]:
    """Return display text and badge class for status."""
    return get_status_display(status)


__all__ = ["_get_status_display", "_unix_to_datetime"]