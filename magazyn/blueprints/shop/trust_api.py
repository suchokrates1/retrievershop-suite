"""Publiczne API sygnałów zaufania / katalogu dla WordPress."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ...csrf_extension import csrf
from ...services.allegro_ratings_snapshot import get_public_snapshot
from ...services.allegro_reviews_snapshot import get_public_reviews
from ...services.shop_catalog import get_shop_bestsellers, get_shop_latest_delivery

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


@bp.route("/api/shop-trust/reviews", methods=["GET"])
@csrf.exempt
def allegro_reviews():
    """Lista opinii Allegro z komentarzem (do karuzeli na homepage)."""
    try:
        limit = int(request.args.get("limit", 12))
    except (TypeError, ValueError):
        limit = 12
    data = get_public_reviews(limit=limit, refresh_if_stale=True)
    if not data or not data.get("reviews"):
        return jsonify({"ok": False, "error": "reviews_unavailable"}), 503
    return jsonify({"ok": True, **data}), 200


@bp.route("/api/shop-trust/bestsellers", methods=["GET"])
@csrf.exempt
def shop_bestsellers():
    """Top sprzedawane produkty (zmapowane do Woo) z ostatnich N dni."""
    try:
        limit = int(request.args.get("limit", 8))
    except (TypeError, ValueError):
        limit = 8
    try:
        days = int(request.args.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    return jsonify(get_shop_bestsellers(limit=limit, days=days)), 200


@bp.route("/api/shop-trust/latest-delivery", methods=["GET"])
@csrf.exempt
def shop_latest_delivery():
    """Produkty z ostatniej dostawy (purchase_batches) zmapowane do Woo."""
    try:
        limit = int(request.args.get("limit", 8))
    except (TypeError, ValueError):
        limit = 8
    return jsonify(get_shop_latest_delivery(limit=limit)), 200
