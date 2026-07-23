"""Publiczne API faktur PDF dla WordPress (Bearer / HMAC)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re

from flask import Blueprint, Response, jsonify, request

from ...csrf_extension import csrf
from ...db import get_session
from ...models.orders import Order
from ...settings_store import settings_store

logger = logging.getLogger(__name__)

bp = Blueprint("shop_invoice_api", __name__)


def _shop_secret() -> str:
    return (
        settings_store.get("NEWSLETTER_MAIL_SECRET")
        or settings_store.get("WOO_WEBHOOK_SECRET")
        or settings_store.get("WOO_RETURN_WEBHOOK_SECRET")
        or ""
    )


def _authorized(body: bytes) -> bool:
    secret = _shop_secret()
    if not secret:
        return False
    bearer = request.headers.get("Authorization", "")
    if bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:].strip(), secret):
        return True
    signature = (
        request.headers.get("X-RS-Invoice-Signature", "")
        or request.headers.get("X-RS-Mail-Signature", "")
    )
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    sig = signature.strip()
    if sig.startswith("sha256="):
        sig = sig[7:]
    return hmac.compare_digest(digest, sig)


def _find_woo_order(db, woo_id: int) -> Order | None:
    order_id = f"woo_{woo_id}"
    order = db.query(Order).filter(Order.order_id == order_id).first()
    if order:
        return order
    order = (
        db.query(Order)
        .filter(Order.external_order_id == str(woo_id))
        .filter(Order.platform == "woocommerce")
        .first()
    )
    if order:
        return order
    if hasattr(Order, "shop_order_id"):
        return db.query(Order).filter(Order.shop_order_id == woo_id).first()
    return None


def _safe_filename(number: str | None) -> str:
    raw = (number or "faktura").strip() or "faktura"
    raw = re.sub(r'[\\/:*?"<>|]+', "_", raw)
    return f"{raw}.pdf"


@bp.route("/api/shop/orders/<int:woo_id>/invoice/status", methods=["GET", "OPTIONS"])
@csrf.exempt
def invoice_status(woo_id: int):
    if request.method == "OPTIONS":
        return ("", 204)
    if not _authorized(request.get_data() or b""):
        return jsonify({"error": "unauthorized"}), 401

    with get_session() as db:
        order = _find_woo_order(db, woo_id)
        if not order or not order.wfirma_invoice_id:
            return jsonify({"available": False}), 200
        return jsonify(
            {
                "available": True,
                "invoice_number": order.wfirma_invoice_number or "",
                "wfirma_invoice_id": int(order.wfirma_invoice_id),
            }
        ), 200


@bp.route("/api/shop/orders/<int:woo_id>/invoice.pdf", methods=["GET", "OPTIONS"])
@csrf.exempt
def invoice_pdf(woo_id: int):
    if request.method == "OPTIONS":
        return ("", 204)
    if not _authorized(request.get_data() or b""):
        return jsonify({"error": "unauthorized"}), 401

    with get_session() as db:
        order = _find_woo_order(db, woo_id)
        if not order or not order.wfirma_invoice_id:
            return jsonify({"error": "not_found"}), 404

        invoice_id = int(order.wfirma_invoice_id)
        invoice_number = order.wfirma_invoice_number
        try:
            from ...wfirma_api import WFirmaClient, download_invoice_pdf

            client = WFirmaClient.from_settings()
            pdf_data = download_invoice_pdf(client, invoice_id)
        except Exception as exc:
            logger.error(
                "shop invoice.pdf: blad pobierania woo=%s wfirma=%s: %s",
                woo_id,
                invoice_id,
                exc,
            )
            return jsonify({"error": "pdf_unavailable"}), 502

        filename = _safe_filename(invoice_number)
        return Response(
            pdf_data,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
            },
        )
