"""Publiczne API instrukcji zwrotu (token z URL)."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ...csrf_extension import csrf
from ...services.return_ship_instructions import (
    choose_return_ship_method,
    get_instructions_payload,
)

logger = logging.getLogger(__name__)

bp = Blueprint("shop_return_instructions_api", __name__)


def _cors(response):
    origin = (request.headers.get("Origin") or "").strip()
    if origin.endswith("://retrievershop.pl") or origin.endswith(".retrievershop.pl"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
        response.headers["Vary"] = "Origin"
    return response


@bp.after_request
def return_instructions_cors(response):
    return _cors(response)


@bp.route("/api/shop/return-instructions/<token>", methods=["GET", "OPTIONS"])
@csrf.exempt
def get_return_instructions(token: str):
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True})), 204
    payload = get_instructions_payload(token)
    status = 200 if payload.get("ok") else 404
    return jsonify(payload), status


@bp.route("/api/shop/return-instructions/<token>/choose", methods=["POST", "OPTIONS"])
@csrf.exempt
def choose_return_instructions(token: str):
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True})), 204
    body = request.get_json(silent=True) or {}
    method = (body.get("method") or "").strip()
    pack_size = (body.get("pack_size") or body.get("size") or "A").strip()
    phone = body.get("phone")
    result = choose_return_ship_method(
        token,
        method,
        pack_size=pack_size,
        phone=phone if isinstance(phone, str) else None,
    )
    if result.get("ok"):
        return jsonify(result), 200
    err = result.get("error")
    code = 400
    if err == "not_found":
        code = 404
    elif err == "inpost_unavailable":
        code = 503
    elif err == "phone_required":
        code = 422
    elif err == "method_locked":
        code = 409
    return jsonify(result), code
