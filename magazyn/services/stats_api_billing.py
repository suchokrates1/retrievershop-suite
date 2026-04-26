"""Endpointy slownika billing types API statystyk."""

from __future__ import annotations

from .stats_endpoint_context import (
    AllegroBillingType,
    BILLING_CATEGORY_CHOICES,
    _json_error,
    datetime,
    get_session,
    jsonify,
    request,
    settings_store,
    sync_billing_types_dictionary,
    timezone,
)


def stats_billing_types_list():
    with get_session() as db:
        rows = (
            db.query(AllegroBillingType)
            .order_by(AllegroBillingType.type_id.asc())
            .all()
        )

    data = [
        {
            "type_id": row.type_id,
            "name": row.name,
            "description": row.description,
            "mapping_category": row.mapping_category,
            "mapping_version": int(row.mapping_version or 1),
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row in rows
    ]
    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": {
                "rows": data,
                "categories": sorted(BILLING_CATEGORY_CHOICES),
            },
            "errors": [],
        }
    )


def stats_billing_type_update(type_id: str):
    payload = request.get_json(silent=True) or {}
    new_category = (payload.get("mapping_category") or "").strip()
    if new_category not in BILLING_CATEGORY_CHOICES:
        return _json_error(
            "INVALID_MAPPING_CATEGORY",
            "Niepoprawna kategoria mapowania billing type",
            400,
        )

    with get_session() as db:
        row = db.query(AllegroBillingType).filter(AllegroBillingType.type_id == type_id).first()
        if row is None:
            return _json_error("BILLING_TYPE_NOT_FOUND", "Nie znaleziono billing type", 404)

        if row.mapping_category != new_category:
            row.mapping_category = new_category
            row.mapping_version = int(row.mapping_version or 1) + 1
            db.flush()

        result = {
            "type_id": row.type_id,
            "mapping_category": row.mapping_category,
            "mapping_version": int(row.mapping_version or 1),
        }

    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": result,
            "errors": [],
        }
    )


def stats_billing_types_sync():
    access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not access_token:
        return _json_error("ALLEGRO_TOKEN_MISSING", "Brak tokenu Allegro", 400)

    result = sync_billing_types_dictionary(access_token)
    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": result,
            "errors": [],
        }
    )
