"""
Blueprint publicznej strony zamowienia dla klienta.

Dostepna bez logowania - autoryzacja przez unikalny token w URL.
Strona zamowienia z danymi, trackingiem, faktura.
"""

import logging
from datetime import datetime, timezone

from flask import Blueprint, render_template, abort, Response

from ..db import get_session
from ..models.orders import Order, OrderStatusLog
from ..services.tracking import get_tracking_url
from ..status_config import (
    CUSTOMER_STATUS_DISPLAY as CUSTOMER_STATUS_MAP_CONFIG,
    CUSTOMER_STAGES,
    CUSTOMER_STAGE_MAP,
)

logger = logging.getLogger(__name__)

bp = Blueprint("customer_order", __name__)


# Mapowanie statusow na czytelne opisy dla klienta
CUSTOMER_STATUS_MAP = {
    status: info for status, info in CUSTOMER_STATUS_MAP_CONFIG.items()
}

# Etapy realizacji widoczne dla klienta (z status_config)
# CUSTOMER_STAGES imported from status_config

# Mapowanie statusow wewnetrznych na etap klienta
STATUS_TO_STAGE = dict(CUSTOMER_STAGE_MAP)


def _unix_to_datetime(ts):
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _get_current_status(order):
    """Okresl aktualny status zamowienia na podstawie historii."""
    with get_session() as db:
        last_log = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order.order_id)
            .order_by(OrderStatusLog.timestamp.desc())
            .first()
        )
        if last_log:
            return last_log.status
    # Fallback
    return "pobrano"


@bp.route("/zamowienie/<token>")
def customer_order_page(token):
    """Publiczna strona zamowienia dostepna dla klienta przez token."""
    if not token or len(token) < 16:
        abort(404)

    with get_session() as db:
        order = (
            db.query(Order)
            .filter(Order.customer_token == token)
            .first()
        )
        if not order:
            abort(404)

        # Produkty
        products = []
        total_products = 0
        for op in order.products:
            price = float(op.price_brutto) if op.price_brutto else 0
            products.append({
                "name": op.name or "Produkt",
                "quantity": op.quantity or 1,
                "price": price,
                "ean": op.ean,
                "attributes": op.attributes,
            })
            total_products += (op.quantity or 1)

        # Suma zamowienia
        products_total = sum(
            p["price"] * p["quantity"] for p in products
        )
        delivery_cost = float(order.delivery_price) if order.delivery_price else 0
        order_total = products_total + delivery_cost

        # Status
        current_status = _get_current_status(order)
        status_info = CUSTOMER_STATUS_MAP.get(
            current_status, ("W realizacji", "info", "bi-hourglass-split")
        )

        # Etap na progress barze
        current_stage = STATUS_TO_STAGE.get(current_status, 0)
        if current_status == "anulowano":
            current_stage = -1

        # Tracking
        tracking_url = None
        tracking_number = order.delivery_package_nr
        if tracking_number:
            try:
                tracking_url = get_tracking_url(
                    order.courier_code,
                    order.delivery_package_module,
                    tracking_number,
                    order.delivery_method,
                )
            except Exception as exc:
                logger.debug("Nie udało się zbudować linku śledzenia %s: %s", tracking_number, exc)

        # Historia statusow
        status_history = []
        logs = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order.order_id)
            .order_by(OrderStatusLog.timestamp.asc())
            .all()
        )
        for log in logs:
            info = CUSTOMER_STATUS_MAP.get(log.status)
            if info:
                status_history.append({
                    "label": info[0],
                    "icon": info[2],
                    "timestamp": log.timestamp,
                })

        # Dane do faktury
        invoice_data = None
        if order.want_invoice:
            invoice_data = {
                "company": order.invoice_company,
                "nip": order.invoice_nip,
                "name": order.invoice_fullname,
                "address": order.invoice_address,
                "city": order.invoice_city,
                "postcode": order.invoice_postcode,
            }

        context = {
            "order": order,
            "products": products,
            "total_products": total_products,
            "products_total": products_total,
            "delivery_cost": delivery_cost,
            "order_total": order_total,
            "current_status": current_status,
            "status_label": status_info[0],
            "status_color": status_info[1],
            "status_icon": status_info[2],
            "current_stage": current_stage,
            "stages": CUSTOMER_STAGES,
            "tracking_number": tracking_number,
            "tracking_url": tracking_url,
            "delivery_method": order.delivery_method,
            "status_history": status_history,
            "invoice_data": invoice_data,
            "date_add": _unix_to_datetime(order.date_add),
            "wfirma_invoice_id": order.wfirma_invoice_id,
            "wfirma_invoice_number": order.wfirma_invoice_number,
            "wfirma_correction_id": order.wfirma_correction_id,
            "wfirma_correction_number": order.wfirma_correction_number,
        }

        return render_template("customer/order_status.html", **context)


@bp.route("/zamowienie/<token>/faktura")
def customer_invoice_pdf(token):
    """Pobierz PDF faktury - autoryzacja przez token."""
    if not token or len(token) < 16:
        abort(404)

    with get_session() as db:
        order = db.query(Order).filter(Order.customer_token == token).first()
        if not order or not order.wfirma_invoice_id:
            abort(404)

        try:
            from ..wfirma_api import WFirmaClient, download_invoice_pdf
            client = WFirmaClient.from_settings()
            pdf_data = download_invoice_pdf(client, order.wfirma_invoice_id)
        except Exception as exc:
            logger.error("Blad pobierania PDF faktury klienta %s: %s", order.wfirma_invoice_number, exc)
            abort(500)

        safe_nr = (order.wfirma_invoice_number or "faktura").replace("/", "_").replace("\\", "_")
        return Response(
            pdf_data,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"inline; filename={safe_nr}.pdf"},
        )


@bp.route("/zamowienie/<token>/korekta")
def customer_correction_pdf(token):
    """Pobierz PDF korekty faktury - autoryzacja przez token."""
    if not token or len(token) < 16:
        abort(404)

    with get_session() as db:
        order = db.query(Order).filter(Order.customer_token == token).first()
        if not order or not order.wfirma_correction_id:
            abort(404)

        try:
            from ..wfirma_api import WFirmaClient, download_invoice_pdf
            client = WFirmaClient.from_settings()
            pdf_data = download_invoice_pdf(client, order.wfirma_correction_id)
        except Exception as exc:
            logger.error("Blad pobierania PDF korekty klienta %s: %s", order.wfirma_correction_number, exc)
            abort(500)

        safe_nr = (order.wfirma_correction_number or "korekta").replace("/", "_").replace("\\", "_")
        return Response(
            pdf_data,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"inline; filename={safe_nr}.pdf"},
        )
