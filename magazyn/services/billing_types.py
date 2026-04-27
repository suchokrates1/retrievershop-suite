"""Synchronizacja i mapowanie typow billingowych Allegro."""

from __future__ import annotations

from datetime import datetime, timezone

from ..db import get_session
from ..models.allegro import AllegroBillingType


BILLING_CATEGORY_CHOICES = {
    "commission_organic",
    "commission_promoted",
    "shipping",
    "promo",
    "ads",
    "listing",
    "refund",
    "bonus",
    "other",
}


def _default_billing_mapping_category(type_id: str) -> str:
    from ..allegro_api.billing import (
        CAMPAIGN_BONUS_TYPES,
        LISTING_TYPES,
        ORGANIC_COMMISSION_TYPES,
        PROMOTED_COMMISSION_TYPES,
        PROMO_TYPES,
        REFUND_TYPES,
        SHIPPING_TYPES,
    )

    if type_id in ORGANIC_COMMISSION_TYPES:
        return "commission_organic"
    if type_id in PROMOTED_COMMISSION_TYPES:
        return "commission_promoted"
    if type_id in SHIPPING_TYPES:
        return "shipping"
    if type_id in PROMO_TYPES:
        if type_id in {"NSP", "ADS"}:
            return "ads"
        return "promo"
    if type_id in LISTING_TYPES:
        return "listing"
    if type_id in REFUND_TYPES:
        return "refund"
    if type_id in CAMPAIGN_BONUS_TYPES:
        return "bonus"
    return "other"


def _upsert_billing_types(db, billing_types: list[dict]) -> dict[str, str]:
    """Synchronizuje slownik billing types do bazy i zwraca mapowanie id->nazwa."""
    now = datetime.now(timezone.utc)
    existing = {row.type_id: row for row in db.query(AllegroBillingType).all()}

    for item in billing_types:
        type_id = (item.get("id") or "").strip()
        if not type_id:
            continue

        name = (item.get("description") or item.get("name") or type_id).strip()
        description = (item.get("description") or item.get("name") or "").strip() or None

        inferred_category = _default_billing_mapping_category(type_id)
        row = existing.get(type_id)
        if row is None:
            row = AllegroBillingType(
                type_id=type_id,
                name=name,
                description=description,
                mapping_category=inferred_category,
                mapping_version=1,
                last_seen_at=now,
            )
            db.add(row)
            existing[type_id] = row
        else:
            row.name = name
            row.description = description
            if not row.mapping_category:
                row.mapping_category = inferred_category
            row.last_seen_at = now

    db.flush()
    return {row.type_id: (row.name or row.type_id) for row in existing.values()}


def sync_billing_types_dictionary(access_token: str) -> dict[str, int]:
    """Synchronizuje slownik billing types z Allegro do bazy danych."""
    from ..allegro_api import fetch_billing_types

    types_data = fetch_billing_types(access_token)
    if isinstance(types_data, dict):
        types_list = types_data.get("billingTypes", [])
    else:
        types_list = types_data or []

    with get_session() as db:
        before = db.query(AllegroBillingType).count()
        _upsert_billing_types(db, types_list)
        after = db.query(AllegroBillingType).count()

    return {
        "fetched": len(types_list),
        "known": after,
        "created": max(after - before, 0),
    }


__all__ = [
    "BILLING_CATEGORY_CHOICES",
    "_default_billing_mapping_category",
    "_upsert_billing_types",
    "sync_billing_types_dictionary",
]