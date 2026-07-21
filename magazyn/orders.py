"""Orders blueprint - zarzadzanie zamowieniami."""
import logging
import os

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for, current_app, after_this_request, send_file, jsonify

from .auth import login_required
from .config import settings
from .db import get_session
from .models.orders import Order, OrderStatusLog
from .services.order_creation import build_manual_order_payload
from .services.order_detail_view import build_order_detail_view_context
from .services.order_label_download import prepare_order_label_download
from .services.order_list import build_orders_list_context
from .services.order_sync import sync_order_from_data
from .services.order_labels import reprint_order_labels
from .services.manual_order_actions import apply_manual_tracking, finalize_manual_order_creation, is_manual_order
from .services.order_return_actions import (
    create_manual_return_for_order,
    mark_return_delivered_for_order,
    process_bank_transfer_refund_for_order,
    process_refund_for_order,
    refund_eligibility_for_order,
    restore_return_stock_for_order,
)
from .status_config import VALID_STATUSES

logger = logging.getLogger(__name__)


bp = Blueprint("orders", __name__)

# SHIPPING_STAGES i RETURN_STAGES przeniesione do services/order_detail_builder.py


@bp.route("/orders")
@login_required
def orders_list():
    """Display paginated list of orders with filtering and sorting."""
    return render_template("orders_list.html", **build_orders_list_context(request.args))


@bp.route("/order/<order_id>")
@login_required
def order_detail(order_id: str):
    """Display detailed view of a single order."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            abort(404)
        
        context = build_order_detail_view_context(
            db,
            order,
            app_base_url=getattr(settings, "APP_BASE_URL", "") or "",
        )
        
        rendered = render_template("order_detail.html", **context)
        
        # Zapobiegaj cache przegladarki
        response = current_app.make_response(rendered)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


@bp.route("/order/<order_id>/invoice-pdf")
@login_required
def download_invoice_pdf(order_id: str):
    """Pobierz PDF faktury z wFirma."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order or not order.wfirma_invoice_id:
            abort(404)

        try:
            from .wfirma_api import WFirmaClient
            from .wfirma_api import download_invoice_pdf as wfirma_download
            client = WFirmaClient.from_settings()
            pdf_data = wfirma_download(client, order.wfirma_invoice_id)
        except Exception as exc:
            logger.error("Blad pobierania PDF faktury %s: %s", order.wfirma_invoice_number, exc)
            flash("Blad pobierania PDF faktury", "error")
            return redirect(url_for(".order_detail", order_id=order_id))

        safe_nr = (order.wfirma_invoice_number or "faktura").replace("/", "_").replace("\\", "_")
        from flask import Response
        return Response(
            pdf_data,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"inline; filename={safe_nr}.pdf"},
        )


@bp.route("/order/<order_id>/correction-pdf")
@login_required
def download_correction_pdf(order_id: str):
    """Pobierz PDF korekty faktury z wFirma."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order or not order.wfirma_correction_id:
            abort(404)

        try:
            from .wfirma_api import WFirmaClient
            from .wfirma_api import download_invoice_pdf as wfirma_download
            client = WFirmaClient.from_settings()
            pdf_data = wfirma_download(client, order.wfirma_correction_id)
        except Exception as exc:
            logger.error("Blad pobierania PDF korekty %s: %s", order.wfirma_correction_number, exc)
            flash("Blad pobierania PDF korekty", "error")
            return redirect(url_for(".order_detail", order_id=order_id))

        safe_nr = (order.wfirma_correction_number or "korekta").replace("/", "_").replace("\\", "_")
        from flask import Response
        return Response(
            pdf_data,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"inline; filename={safe_nr}.pdf"},
        )


@bp.route("/order/<order_id>/update_status", methods=["POST"])
@login_required
def update_order_status(order_id: str):
    """Update order status."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            abort(404)
        
        new_status = request.form.get("status")
        tracking_number = request.form.get("tracking_number", "").strip() or None
        courier_code = request.form.get("courier_code", "").strip() or None
        notes = request.form.get("notes", "").strip() or None
        
        if new_status not in VALID_STATUSES:
            flash("Nieprawidłowy status", "error")
            return redirect(url_for(".order_detail", order_id=order_id))
        
        # Create status log entry
        status_log = OrderStatusLog(
            order_id=order_id,
            status=new_status,
            tracking_number=tracking_number,
            courier_code=courier_code,
            notes=notes,
        )
        db.add(status_log)
        
        # Update order tracking info if provided
        if tracking_number:
            order.delivery_package_nr = tracking_number
        if courier_code:
            order.courier_code = courier_code
        
        db.commit()
        
        flash("Status zamówienia zaktualizowany", "success")
        return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/reprint", methods=["POST"])
@login_required
def reprint_label(order_id: str):
    """Reprint shipping label for an order."""
    try:
        result = reprint_order_labels(order_id)
        flash(result.message, result.category)
    except Exception as exc:
        logger.exception("Blad drukowania etykiety dla zamowienia %s", order_id)
        flash(f"Błąd drukowania: {exc}", "error")
    
    # Redirect back to wherever the user came from
    referrer = request.referrer
    if referrer and "order" in referrer:
        return redirect(referrer)
    return redirect(url_for(".orders_list"))


@bp.route("/order/<order_id>/restore_return_stock", methods=["POST"])
@login_required
def restore_return_stock(order_id: str):
    """Recznie przywroc stan magazynowy dla zwrotu."""
    result = restore_return_stock_for_order(order_id)
    flash(result.message, result.category)
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/create_manual_return", methods=["POST"])
@login_required
def create_manual_return(order_id: str):
    """Ręcznie utwórz zwrot poza Allegro z karty zamówienia."""
    result = create_manual_return_for_order(order_id, request.form)
    if result.not_found:
        abort(404)
    flash(result.message, result.category)
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/mark_return_delivered", methods=["POST"])
@login_required
def mark_return_delivered(order_id: str):
    """Ręcznie oznacz zwrot jako odebrany."""
    result = mark_return_delivered_for_order(order_id)
    flash(result.message, result.category)
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/check_refund_eligibility", methods=["GET"])
@login_required
def check_refund_eligibility(order_id: str):
    """
    Sprawdz czy zamowienie kwalifikuje sie do zwrotu pieniedzy.
    
    Zwraca JSON z informacjami o kwocie i statusie.
    """
    return jsonify(refund_eligibility_for_order(order_id))


@bp.route("/order/<order_id>/process_refund", methods=["POST"])
@login_required
def process_refund(order_id: str):
    """
    Przetworz zwrot pieniedzy dla zamowienia.
    
    UWAGA: Ta operacja jest NIEODWRACALNA!
    
    Wymaga potwierdzenia przez:
    1. Pole confirm=true w POST
    2. Pole allegro_return_id musi zgadzac sie z baza
    """
    result = process_refund_for_order(order_id, request.form, request.get_json(silent=True))
    flash(result.message, result.category)
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/process_bank_transfer_refund", methods=["POST"])
@login_required
def process_bank_transfer_refund(order_id: str):
    """Oznacz zwrot przelewem bankowym (np. pobranie) i wystaw korekte."""
    result = process_bank_transfer_refund_for_order(
        order_id, request.form, request.get_json(silent=True)
    )
    flash(result.message, result.category)
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/cancel", methods=["POST"])
@login_required
def cancel_order_route(order_id: str):
    """Anuluj zamowienie (korekta, status, Allegro CANCELLED, opcjonalnie refund)."""
    from .services.order_cancel import cancel_order

    money_already_refunded = request.form.get("money_already_refunded") in (
        "1", "true", "on", "yes",
    )
    reason = (request.form.get("reason") or "").strip()
    result = cancel_order(
        order_id,
        money_already_refunded=money_already_refunded,
        reason=reason,
    )
    if result.not_found:
        abort(404)
    flash(result.message, result.category)
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/item/<int:order_product_id>/variant_options", methods=["GET"])
@login_required
def order_item_variant_options(order_id: str, order_product_id: int):
    """JSON: dostepne warianty koloru/rozmiaru dla pozycji."""
    from .services.order_item_edit import list_variant_options

    return jsonify(list_variant_options(order_id, order_product_id))


@bp.route("/order/<order_id>/edit_item", methods=["POST"])
@login_required
def edit_order_item(order_id: str):
    """Zmien kolor/rozmiar pozycji zamowienia."""
    from .services.order_item_edit import edit_order_item_variant

    try:
        order_product_id = int(request.form.get("order_product_id") or 0)
        new_product_size_id = int(request.form.get("new_product_size_id") or 0)
    except (TypeError, ValueError):
        flash("Nieprawidlowe dane edycji wariantu", "error")
        return redirect(url_for(".order_detail", order_id=order_id))

    restore_previous_stock = request.form.get("restore_previous_stock") in (
        "1", "true", "on", "yes",
    )
    result = edit_order_item_variant(
        order_id,
        order_product_id,
        new_product_size_id,
        restore_previous_stock=restore_previous_stock,
    )
    if result.not_found:
        abort(404)
    flash(result.message, result.category)
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/download_label", methods=["GET"])
@login_required
def download_label(order_id: str):
    """Download shipping label PDF for an order."""
    from .services.print_agent_runtime import agent as label_agent
    
    try:
        prepared_label = prepare_order_label_download(order_id, label_agent)
        if prepared_label:
            @after_this_request
            def remove_file(response):
                try:
                    os.remove(prepared_label.path)
                except OSError as exc:
                    current_app.logger.debug(
                        "Nie udało się usunąć tymczasowej etykiety %s: %s",
                        prepared_label.path,
                        exc,
                    )
                return response

            return send_file(
                prepared_label.path,
                as_attachment=True,
                download_name=prepared_label.filename,
                mimetype=prepared_label.mimetype,
            )
        
        flash("Nie znaleziono etykiety do pobrania", "warning")
            
    except Exception as exc:
        flash(f"Błąd pobierania etykiety: {exc}", "error")
    
    return redirect(url_for(".order_detail", order_id=order_id))



@bp.route("/orders/add", methods=["GET", "POST"])
@login_required
def add_order():
    """Dodaj zamowienie reczne (OLX, sklep, inne platformy)."""
    if request.method == "GET":
        return render_template("add_order.html")

    payload = build_manual_order_payload(request.form)
    if payload.error:
        flash(payload.error, "danger")
        return render_template("add_order.html")

    with get_session() as db:
        order = sync_order_from_data(db, payload.order_data)
        finalize_manual_order_creation(db, order, payload.order_data)
        db.commit()
        flash(f"Zamowienie {order.order_id} zostalo utworzone.", "success")
        return redirect(url_for("orders.order_detail", order_id=order.order_id))


@bp.route("/order/<order_id>/manual_tracking", methods=["POST"])
@login_required
def update_manual_tracking(order_id: str):
    """Dodaj lub zmien nr przesylki w zamowieniu recznym."""
    tracking_number = request.form.get("tracking_number", "").strip()
    courier_code = request.form.get("courier_code", "").strip() or None

    if not tracking_number:
        flash("Podaj numer przesylki", "danger")
        return redirect(url_for(".order_detail", order_id=order_id))

    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            abort(404)
        if not is_manual_order(order):
            flash("Ta akcja jest dostepna tylko dla zamowien recznych", "danger")
            return redirect(url_for(".order_detail", order_id=order_id))

        try:
            apply_manual_tracking(
                db,
                order,
                tracking_number,
                courier_code=courier_code,
                notes="Numer przesylki dodany recznie",
            )
            db.commit()
            flash("Numer przesylki zapisany", "success")
        except ValueError as exc:
            flash(str(exc), "danger")

    return redirect(url_for(".order_detail", order_id=order_id))


# Synchronizacja statusów przesyłek jest automatyczna (co godzinę w schedulerze)
# Nie potrzebujemy ręcznej synchronizacji ani osobnego widoku śledzenia
# Historia wysyłki jest zintegrowana w order_detail.html
