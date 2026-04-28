"""Orders blueprint - zarzadzanie zamowieniami."""
import logging
import os

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for, current_app, after_this_request, send_file, jsonify

from .auth import login_required
from .config import settings
from .db import get_session
from .models.orders import Order, OrderStatusLog
from .services.order_allegro_sync import sync_orders_from_allegro_api
from .services.order_creation import build_manual_order_payload
from .services.order_detail_view import build_order_detail_view_context
from .services.order_label_download import prepare_order_label_download
from .services.order_list import build_orders_list_context
from .services.order_sync import sync_order_from_data
from .services.order_status import add_order_status
from .services.order_labels import reprint_order_labels
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
    from .models.returns import Return
    from .services.return_stock import restore_stock_for_return
    
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        
        if not return_record:
            flash(f"Nie znaleziono zwrotu dla zamowienia {order_id}", "error")
        elif return_record.stock_restored:
            flash("Stan juz zostal przywrocony", "warning")
        else:
            if restore_stock_for_return(return_record.id):
                flash("Stan magazynowy zostal przywrocony", "success")
            else:
                flash("Nie udalo sie przywrocic stanu - sprawdz czy produkty sa powiazane z magazynem", "error")
    
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/check_refund_eligibility", methods=["GET"])
@login_required
def check_refund_eligibility(order_id: str):
    """
    Sprawdz czy zamowienie kwalifikuje sie do zwrotu pieniedzy.
    
    Zwraca JSON z informacjami o kwocie i statusie.
    """
    from .services.return_refunds import check_refund_eligibility as check_eligibility
    
    eligible, message, details = check_eligibility(order_id)
    
    return jsonify({
        "eligible": eligible,
        "message": message,
        "details": details
    })


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
    from .models.returns import Return
    from .services.return_refunds import process_refund as do_refund, check_refund_eligibility as check_eligibility
    
    # Sprawdz czy potwierdzono operacje
    confirm = request.form.get("confirm") == "true" or request.json and request.json.get("confirm") is True
    if not confirm:
        flash("Operacja wymaga potwierdzenia", "error")
        return redirect(url_for(".order_detail", order_id=order_id))
    
    # Dodatkowa walidacja - sprawdz allegro_return_id
    expected_return_id = request.form.get("allegro_return_id") or (request.json and request.json.get("allegro_return_id"))
    
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        
        if not return_record:
            flash("Nie znaleziono zwrotu dla tego zamowienia", "error")
            return redirect(url_for(".order_detail", order_id=order_id))
        
        if return_record.allegro_return_id != expected_return_id:
            flash("Blad walidacji - ID zwrotu Allegro nie zgadza sie", "error")
            return redirect(url_for(".order_detail", order_id=order_id))
    
    # Sprawdz jeszcze raz kwalifikowalnosc
    eligible, check_message, _ = check_eligibility(order_id)
    if not eligible:
        flash(f"Zwrot nie kwalifikuje sie: {check_message}", "error")
        return redirect(url_for(".order_detail", order_id=order_id))
    
    # Opcjonalne parametry
    delivery_cost_covered = request.form.get("delivery_cost_covered", "true") == "true"
    reason = request.form.get("reason", "")
    
    # Wykonaj zwrot
    success, message = do_refund(
        order_id=order_id,
        delivery_cost_covered=delivery_cost_covered,
        reason=reason
    )
    
    if success:
        flash(f"Zwrot pieniedzy zainicjowany pomyslnie! {message}", "success")
    else:
        flash(f"Blad zwrotu pieniedzy: {message}", "error")
    
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/download_label", methods=["GET"])
@login_required
def download_label(order_id: str):
    """Download shipping label PDF for an order."""
    from .print_agent import agent as label_agent
    
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



@bp.route("/orders/api/products/search")
@login_required
def api_product_search():
    """API wyszukiwania produktow do formularza recznego zamowienia."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    with get_session() as db:
        from .models.products import Product, ProductSize
        query = (
            db.query(ProductSize)
            .join(Product, Product.id == ProductSize.product_id)
            .filter(ProductSize.quantity > 0)
        )

        # Szukaj po barcode, nazwie, kolorze, serii
        like_q = f"%{q}%"
        query = query.filter(
            (ProductSize.barcode.ilike(like_q))
            | (Product._name.ilike(like_q))
            | (Product.color.ilike(like_q))
            | (Product.series.ilike(like_q))
            | (Product.category.ilike(like_q))
            | (Product.brand.ilike(like_q))
        )

        results = []
        for ps in query.limit(20).all():
            product = ps.product
            label = f"{product.name} | {product.color or '-'} | {ps.size} | EAN: {ps.barcode or '-'} | Stan: {ps.quantity}"
            results.append({
                "name": f"{product.name} - {product.color or ''} - {ps.size}".strip(" -"),
                "ean": ps.barcode or "",
                "size": ps.size,
                "stock": ps.quantity,
                "label": label,
            })

    return jsonify(results)


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
        add_order_status(db, order.order_id, "pobrano",
                         notes=f"Zamowienie reczne ({payload.order_data['platform']})")
        db.commit()
        flash(f"Zamowienie {order.order_id} zostalo utworzone.", "success")
        return redirect(url_for("orders.order_detail", order_id=order.order_id))


@bp.route("/orders/sync-all", methods=["POST"])
@login_required
def sync_all_orders():
    """Reczne uruchomienie syncu zamowien z Allegro Events API."""
    try:
        from .order_sync_scheduler import _sync_from_allegro_events
        from flask import current_app as app

        current_app.logger.info("Reczny sync zamowien z Allegro Events API")
        ev_stats = _sync_from_allegro_events(app._get_current_object())
        
        synced = ev_stats.get("orders_synced", 0)
        cancelled = ev_stats.get("orders_cancelled", 0)
        current_app.logger.info(
            "Reczny sync zakonczony: %d zsynchronizowanych, %d anulowanych",
            synced, cancelled,
        )
        flash(
            f"Zsynchronizowano {synced} zamowien z Allegro (anulowane: {cancelled})",
            "success",
        )
    except Exception as exc:
        current_app.logger.error("Blad recznego syncu zamowien: %s", exc)
        flash(f"Blad synchronizacji: {exc}", "error")
    
    return redirect(url_for(".orders_list"))


@bp.route("/orders/sync-allegro", methods=["POST"])
@login_required
def sync_allegro_orders():
    """
    Synchronizacja zamowien bezposrednio z Allegro REST API.
    
    Allegro zwraca zamowienia z ostatnich 12 miesiecy (max).
    Paginacja: offset/limit, max offset+limit = 10000.
    Uzywa GET /order/checkout-forms.
    """
    try:
        current_app.logger.info("Rozpoczynam sync zamowien z Allegro API...")
        with get_session() as db:
            result = sync_orders_from_allegro_api(
                db,
                sync_order_from_data=sync_order_from_data,
                add_order_status=add_order_status,
                logger=current_app.logger,
            )
        current_app.logger.info(result.message)
        flash(result.message, "success")

    except Exception as exc:
        current_app.logger.error("Blad sync zamowien z Allegro API: %s", exc)
        flash(f"Blad synchronizacji z Allegro: {exc}", "error")

    return redirect(url_for(".orders_list"))


# Synchronizacja statusów przesyłek jest automatyczna (co godzinę w schedulerze)
# Nie potrzebujemy ręcznej synchronizacji ani osobnego widoku śledzenia
# Historia wysyłki jest zintegrowana w order_detail.html
