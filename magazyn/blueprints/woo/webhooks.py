"""Webhooki WooCommerce (publiczne, HMAC)."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ...csrf_extension import csrf
from ...services.return_woo import (
    upsert_return_from_woo_withdrawal,
    verify_woo_return_signature,
)
from ...services.woo_order_sync import import_woo_order, verify_woo_webhook_signature

logger = logging.getLogger(__name__)

bp = Blueprint("woocommerce_webhooks", __name__)


@bp.route("/webhooks/woocommerce", methods=["POST"])
@csrf.exempt
def woo_webhook():
    body = request.get_data()
    signature = request.headers.get("X-WC-Webhook-Signature", "")
    if not verify_woo_webhook_signature(body, signature):
        logger.warning("Woo webhook: nieprawidlowy podpis")
        return jsonify({"error": "invalid signature"}), 401

    topic = request.headers.get("X-WC-Webhook-Topic", "")
    payload = request.get_json(silent=True) or {}
    if not payload.get("id"):
        return jsonify({"ok": True, "skipped": "no id"}), 200

    try:
        result = import_woo_order(payload)
        logger.info("Woo webhook %s -> %s", topic, result)
        return jsonify({"ok": True, **result}), 200
    except Exception as exc:
        logger.exception("Woo webhook error")
        return jsonify({"error": str(exc)}), 500


@bp.route("/webhooks/woo-return", methods=["POST"])
@csrf.exempt
def woo_return_webhook():
    """WebToffee EU Withdrawal → magazyn Return."""
    body = request.get_data()
    signature = request.headers.get("X-Retriever-Signature", "")
    if not verify_woo_return_signature(body, signature):
        logger.warning("Woo return webhook: nieprawidlowy podpis")
        return jsonify({"error": "invalid signature"}), 401

    payload = request.get_json(silent=True) or {}
    try:
        result = upsert_return_from_woo_withdrawal(payload)
        status = 200 if result.get("ok") else 404
        logger.info("Woo return webhook -> %s", result)
        return jsonify(result), status
    except Exception as exc:
        logger.exception("Woo return webhook error")
        return jsonify({"ok": False, "error": str(exc)}), 500
