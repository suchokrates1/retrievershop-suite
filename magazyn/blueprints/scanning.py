"""
Blueprint skanowania - obsluga skanowania kodów kreskowych produktów i etykiet.

Wyodrebniony z products.py dla lepszej organizacji kodu.
"""
import json
import time
import logging

from flask import (
    Blueprint,
    render_template,
    request,
    url_for,
    flash,
    jsonify,
    session,
    current_app,
    g,
)
from sqlalchemy import desc

from ..db import get_session
from ..auth import login_required
from ..models.printing import ScanLog
from ..domain.products import find_by_barcode
from ..parsing import parse_product_info
from ..services.scanning import (
    check_and_auto_pack,
    load_order_for_barcode,
    record_scan_event,
)


logger = logging.getLogger(__name__)


bp = Blueprint("scanning", __name__)


def _log_scan(scan_type: str, barcode: str, success: bool, result_data=None, error_message=None):
    """Zapisz zdarzenie skanu do bazy na potrzeby diagnostyki i audytu."""
    user_id = getattr(g, 'user', {}).get('id') if hasattr(g, 'user') else None
    if user_id is None and 'user_id' in session:
        user_id = session.get('user_id')

    record_scan_event(
        scan_type,
        barcode,
        success,
        result_data=result_data,
        error_message=error_message,
        user_id=user_id,
        log=current_app.logger,
    )


def _check_and_auto_pack():
    """Sprawdź, czy ostatnie skany pozwalają automatycznie spakować zamówienie."""
    result = check_and_auto_pack(session, log=current_app.logger)
    if result.state_modified:
        session.modified = True
    if result.flash_message:
        flash(result.flash_message, result.flash_category or 'info')


# ============================================================================
# ENDPOINTY SKANOWANIA
# ============================================================================

@bp.route("/barcode_scan", methods=["POST"])
@login_required
def barcode_scan():
    """Obsłuż skan kodu EAN produktu."""
    data = request.get_json(silent=True) or {}
    barcode = (data.get("barcode") or "").strip()
    if not barcode:
        return ("", 400)
    
    result = find_by_barcode(barcode)
    if result:
        current_app.logger.info(f"[BARCODE_SCAN] EAN: {barcode} -> Referer: {request.headers.get('Referer', 'brak')} -> Result: {json.dumps(result, ensure_ascii=False)}")
        
        _log_scan('product', barcode, True, result)
        
        # Zapamiętaj ostatni skan produktu do automatycznego pakowania.
        scan_timestamp = time.time()
        session['last_product_scan'] = {
            'barcode': barcode,
            'product_size_id': result.get('product_size_id'),
            'timestamp': scan_timestamp,
            'scan_key': f"{barcode}:{scan_timestamp:.6f}",
        }
        
        _check_and_auto_pack()
        
        flash(f'Znaleziono produkt: {result["name"]}')
        return jsonify(result)
    
    _log_scan('product', barcode, False, error_message="Nie znaleziono produktu")
    flash("Nie znaleziono produktu o podanym kodzie kreskowym", "error")
    return ("", 400)


@bp.route("/scan_barcode")
@login_required
def barcode_scan_page():
    """Wyświetl stronę skanowania kodów produktów."""
    next_url = request.args.get("next", url_for("products.items"))
    return render_template("scan_barcode.html", next=next_url)


@bp.route("/label_scan", methods=["POST"])
@login_required
def label_barcode_scan():
    """Obsłuż skan kodu z etykiety wysyłkowej."""
    payload = request.get_json(silent=True) or {}
    barcode = (payload.get("barcode") or "").strip()
    if not barcode:
        return ("", 400)

    order_id, order_data = load_order_for_barcode(barcode)
    if not order_data:
        _log_scan('label', barcode, False, error_message="Nie znaleziono paczki")
        return jsonify({"error": "Nie znaleziono paczki dla zeskanowanej etykiety."}), 404

    products = []
    for item in order_data.get("products", []) or []:
        name, size, color = parse_product_info(item)
        products.append(
            {
                "name": name or item.get("name", ""),
                "size": size,
                "color": color,
                "quantity": item.get("quantity", 0),
            }
        )

    # Zapamiętaj ostatni skan etykiety do automatycznego pakowania.
    session['last_label_scan'] = {
        'order_id': order_id,
        'timestamp': time.time()
    }
    
    _check_and_auto_pack()

    delivery_method = order_data.get("shipping") or order_data.get("delivery_method") or ""
    courier_code = order_data.get("courier_code") or order_data.get("delivery_package_module") or ""

    response = {
        "order_id": order_id or order_data.get("order_id") or "",
        "package_ids": order_data.get("package_ids") or [],
        "products": products,
        "delivery_method": delivery_method,
        "courier_code": courier_code,
    }
    
    _log_scan('label', barcode, True, response)
    
    return jsonify(response)


@bp.route("/scan_label")
@login_required
def label_scan_page():
    """Wyświetl stronę skanowania etykiet wysyłkowych."""
    next_url = request.args.get("next", url_for("products.items"))
    return render_template(
        "scan_label.html",
        next=next_url,
        barcode_mode="label",
        barcode_endpoint=url_for("scanning.label_barcode_scan"),
        barcode_error_message="Nie znaleziono paczki dla zeskanowanej etykiety.",
    )


@bp.route("/scan_logs")
@login_required
def scan_logs():
    """Wyświetl ostatnie logi skanowania do diagnostyki."""
    limit = request.args.get("limit", 20, type=int)
    scan_type = request.args.get("type")  # product, label albo wszystkie
    
    with get_session() as db:
        query = db.query(ScanLog).order_by(desc(ScanLog.created_at))
        if scan_type:
            query = query.filter(ScanLog.scan_type == scan_type)
        logs = query.limit(limit).all()
        
        result = []
        for log in logs:
            result.append({
                "id": log.id,
                "scan_type": log.scan_type,
                "barcode": log.barcode,
                "success": log.success,
                "result_data": json.loads(log.result_data) if log.result_data else None,
                "error_message": log.error_message,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            })
    
    if request.headers.get('Accept') == 'application/json':
        return jsonify(result)
    
    return render_template("scan_logs.html", logs=result)
