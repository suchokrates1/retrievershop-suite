"""Publiczne API maili transakcyjnych dla WordPress (HMAC / Bearer)."""

from __future__ import annotations

import hashlib
import hmac
import logging

from flask import Blueprint, jsonify, request

from ...csrf_extension import csrf
from ...services.email_service import send_contact_form_message, send_newsletter_welcome
from ...settings_store import settings_store

logger = logging.getLogger(__name__)

bp = Blueprint("shop_mail_api", __name__)


def _newsletter_secret() -> str:
    return (
        settings_store.get("NEWSLETTER_MAIL_SECRET")
        or settings_store.get("WOO_WEBHOOK_SECRET")
        or ""
    )


def _authorized(body: bytes) -> bool:
    secret = _newsletter_secret()
    if not secret:
        return False
    bearer = request.headers.get("Authorization", "")
    if bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:].strip(), secret):
        return True
    signature = request.headers.get("X-RS-Mail-Signature", "")
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature.strip())


@bp.route("/api/shop-mail/newsletter-welcome", methods=["POST"])
@csrf.exempt
def newsletter_welcome():
    body = request.get_data()
    if not _authorized(body):
        logger.warning("newsletter-welcome: nieautoryzowane")
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip()
    first_name = (payload.get("first_name") or "").strip()
    coupon_code = (payload.get("coupon_code") or "").strip()
    try:
        discount_percent = int(payload.get("discount_percent") or 10)
    except (TypeError, ValueError):
        discount_percent = 10
    try:
        valid_days = int(payload.get("valid_days") or 30)
    except (TypeError, ValueError):
        valid_days = 30
    shop_url = (payload.get("shop_url") or "https://retrievershop.pl/produkty/").strip()

    if not email or not coupon_code:
        return jsonify({"error": "email and coupon_code required"}), 400

    ok = send_newsletter_welcome(
        to_email=email,
        first_name=first_name,
        coupon_code=coupon_code,
        discount_percent=discount_percent,
        valid_days=valid_days,
        shop_url=shop_url,
    )
    if not ok:
        return jsonify({"ok": False, "error": "smtp_send_failed"}), 502
    return jsonify({"ok": True}), 200


@bp.route("/api/shop-mail/contact", methods=["POST"])
@csrf.exempt
def contact_form():
    body = request.get_data()
    if not _authorized(body):
        logger.warning("shop-mail/contact: nieautoryzowane")
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    phone = (payload.get("phone") or "").strip()
    topic = (payload.get("topic") or "").strip()
    message = (payload.get("message") or "").strip()
    subject = (payload.get("subject") or "").strip()
    source_ip = (payload.get("source_ip") or "").strip()
    page_url = (payload.get("page_url") or "").strip()
    to_email = (payload.get("to_email") or "kontakt@retrievershop.pl").strip()

    if not email or not message:
        return jsonify({"error": "email and message required"}), 400

    ok = send_contact_form_message(
        to_email=to_email,
        reply_to_email=email,
        reply_to_name=name,
        subject=subject,
        topic=topic,
        phone=phone,
        message=message,
        source_ip=source_ip,
        page_url=page_url,
    )
    if not ok:
        return jsonify({"ok": False, "error": "smtp_send_failed"}), 502
    return jsonify({"ok": True}), 200
