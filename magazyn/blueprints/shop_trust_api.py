"""Publiczne API sygnałów zaufania dla WordPress."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from ..csrf_extension import csrf
from ..services.allegro_ratings_snapshot import get_public_snapshot

logger = logging.getLogger(__name__)

bp = Blueprint("shop_trust_api", __name__)


@bp.route("/api/shop-trust/allegro", methods=["GET"])
@csrf.exempt
def allegro_trust():
    """Zwraca zcache'owane podsumowanie ocen Allegro (dane publiczne)."""
    snap = get_public_snapshot(refresh_if_stale=True)
    if not snap:
        return jsonify({"ok": False, "error": "snapshot_unavailable"}), 503
    return jsonify({"ok": True, "allegro": snap}), 200
