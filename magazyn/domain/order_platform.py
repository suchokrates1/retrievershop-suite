"""Rozpoznawanie platformy zamowienia po prefiksie order_id."""

from __future__ import annotations

from typing import Any


def _as_order_id(order_or_id: Any) -> str:
    if order_or_id is None:
        return ""
    if hasattr(order_or_id, "order_id"):
        return str(getattr(order_or_id, "order_id") or "")
    return str(order_or_id)


def is_allegro_order(order_or_id: Any) -> bool:
    return _as_order_id(order_or_id).startswith("allegro_")


def is_woo_order(order_or_id: Any) -> bool:
    return _as_order_id(order_or_id).startswith("woo_")


def is_manual_order(order_or_id: Any) -> bool:
    return _as_order_id(order_or_id).startswith("manual_")


__all__ = ["is_allegro_order", "is_manual_order", "is_woo_order"]
