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

from ..db import get_session, sqlite_connect
from ..auth import login_required
from ..models import PrintedOrder, OrderProduct, OrderStatusLog, ScanLog
from ..domain.products import find_by_barcode
from ..parsing import parse_product_info


logger = logging.getLogger(__name__)


bp = Blueprint("scanning", __name__)


def _log_scan(scan_type: str, barcode: str, success: bool, result_data=None, error_message=None):
    """Log a scan event to the database for debugging and audit."""
    try:
        user_id = getattr(g, 'user', {}).get('id') if hasattr(g, 'user') else None
        if user_id is None and 'user_id' in session:
            user_id = session.get('user_id')
        
        with get_session() as db:
            log = ScanLog(
                scan_type=scan_type,
                barcode=barcode,
                success=success,
                result_data=json.dumps(result_data) if result_data else None,
                error_message=error_message,
                user_id=user_id,
            )
            db.add(log)
    except Exception as e:
        current_app.logger.warning(f"Failed to log scan: {e}")


def _parse_last_order_data(raw):
    """Parse order data from different formats."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _check_and_auto_pack():
    """Check if we can auto-pack: label + matching product scanned within 60 seconds."""
    last_product = session.get('last_product_scan')
    last_label = session.get('last_label_scan')
    
    if not last_product or not last_label:
        current_app.logger.info(f"Auto-pack check: product={bool(last_product)}, label={bool(last_label)}")
        return
    
    # Check if scans are within 60 seconds of each other
    current_time = time.time()
    product_age = current_time - last_product['timestamp']
    label_age = current_time - last_label['timestamp']
    
    current_app.logger.info(f"Auto-pack check: product_age={product_age:.1f}s, label_age={label_age:.1f}s")
    
    if product_age > 60 or label_age > 60:
        current_app.logger.info("Auto-pack: Timeout - scans too old")
        session.pop('last_product_scan', None)
        session.pop('last_label_scan', None)
        session.pop('scanned_products_for_order', None)
        return
    
    order_id = last_label['order_id']
    product_size_id = last_product['product_size_id']
    
    if not order_id or not product_size_id:
        return
    
    with get_session() as db:
        # Get current order status
        latest_status = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order_id)
            .order_by(desc(OrderStatusLog.timestamp))
            .first()
        )
        
        current_status = latest_status.status if latest_status else 'nieznany'
        current_app.logger.info(f"Auto-pack: order_id={order_id}, current_status={current_status}")
        
        # Only auto-pack if current status is "wydrukowano" (after label printed)
        if not latest_status or latest_status.status != "wydrukowano":
            current_app.logger.info(f"Auto-pack: Status nie jest 'wydrukowano' - pomijam")
            return
        
        # Check if product belongs to this order
        order_product = (
            db.query(OrderProduct)
            .filter(
                OrderProduct.order_id == order_id,
                OrderProduct.product_size_id == product_size_id
            )
            .first()
        )
        
        if not order_product:
            current_app.logger.warning(f"Auto-pack: Produkt {product_size_id} NIE należy do zamówienia {order_id}")
            flash('Zeskanowany produkt nie należy do tej paczki!', 'warning')
            return
        
        current_app.logger.info(f"Auto-pack: Produkt {product_size_id} należy do zamówienia {order_id}")
        
        # Track scanned products for this order in session
        scanned_tracking = session.get('scanned_products_for_order', {})
        order_id_str = str(order_id)
        
        if order_id_str not in scanned_tracking:
            scanned_tracking[order_id_str] = []
        
        if product_size_id not in scanned_tracking[order_id_str]:
            scanned_tracking[order_id_str].append(product_size_id)
        
        session['scanned_products_for_order'] = scanned_tracking
        
        # Get all products that should be in this order
        all_order_products = (
            db.query(OrderProduct)
            .filter(OrderProduct.order_id == order_id)
            .all()
        )
        
        required_product_ids = {op.product_size_id for op in all_order_products}
        scanned_product_ids = set(scanned_tracking[order_id_str])
        missing_products = required_product_ids - scanned_product_ids
        
        if missing_products:
            current_app.logger.info(f"Auto-pack: Brakuje produktów: {missing_products}")
            flash(f'Zeskanowano {len(scanned_product_ids)}/{len(required_product_ids)} produktów', 'info')
            return
        
        current_app.logger.info(f"Auto-pack: Wszystkie produkty zeskanowane ({len(required_product_ids)} szt.)")
        
        # All conditions met - change status to "spakowano"
        new_status = OrderStatusLog(
            order_id=order_id,
            status="spakowano",
            notes="Automatycznie spakowano po zeskanowaniu etykiety i produktu"
        )
        db.add(new_status)
        db.commit()
        
        current_app.logger.info(f"AUTO-PACK SUCCESS: Zamówienie {order_id} -> spakowano")
        
        # Clear session data to prevent duplicate packing
        session.pop('last_product_scan', None)
        session.pop('last_label_scan', None)
        
        if 'scanned_products_for_order' in session and order_id_str in session['scanned_products_for_order']:
            session['scanned_products_for_order'].pop(order_id_str, None)
            session.modified = True
        
        flash(f'Spakowano zamówienie {order_id}!', 'success')


def _load_order_for_barcode(barcode: str):
    """Load order data for a given barcode (package ID or tracking number)."""
    import sqlite3
    
    matched_order_id = None
    order_data = None
    barcode = barcode.strip()

    with get_session() as db_session:
        direct = db_session.get(PrintedOrder, barcode)
        if direct:
            matched_order_id = direct.order_id
            order_data = _parse_last_order_data(direct.last_order_data)

        if not order_data:
            for po in db_session.query(PrintedOrder).all():
                data = _parse_last_order_data(po.last_order_data)
                package_ids = data.get("package_ids") or []
                tracking_numbers = data.get("tracking_numbers") or []
                if barcode in package_ids or barcode in tracking_numbers:
                    matched_order_id = po.order_id
                    order_data = data
                    break

    if order_data:
        return matched_order_id, order_data

    try:
        with sqlite_connect() as conn:
            cur = conn.execute(
                "SELECT order_id, last_order_data FROM label_queue"
            )
            for oid, data_json in cur.fetchall():
                data = _parse_last_order_data(data_json)
                package_ids = data.get("package_ids") or []
                tracking_numbers = data.get("tracking_numbers") or []
                if barcode == oid or barcode in package_ids or barcode in tracking_numbers:
                    return oid, data
    except sqlite3.Error:
        pass

    return None, None


# ============================================================================
# ENDPOINTY SKANOWANIA
# ============================================================================

@bp.route("/barcode_scan", methods=["POST"])
@login_required
def barcode_scan():
    """Scan product barcode (EAN)."""
    data = request.get_json(silent=True) or {}
    barcode = (data.get("barcode") or "").strip()
    if not barcode:
        return ("", 400)
    
    result = find_by_barcode(barcode)
    if result:
        current_app.logger.info(f"[BARCODE_SCAN] EAN: {barcode} -> Result: {json.dumps(result, ensure_ascii=False)}")
        
        _log_scan('product', barcode, True, result)
        
        # Store last product scan in session for auto-packing
        session['last_product_scan'] = {
            'barcode': barcode,
            'product_size_id': result.get('product_size_id'),
            'timestamp': time.time()
        }
        
        _check_and_auto_pack()
        
        flash(f'Znaleziono produkt: {result["name"]}')
        return jsonify(result)
    
    _log_scan('product', barcode, False, error_message="Nie znaleziono produktu")
    flash("Nie znaleziono produktu o podanym kodzie kreskowym")
    return ("", 400)


@bp.route("/scan_barcode")
@login_required
def barcode_scan_page():
    """Page for scanning product barcodes."""
    next_url = request.args.get("next", url_for("products.items"))
    return render_template("scan_barcode.html", next=next_url)


@bp.route("/label_scan", methods=["POST"])
@login_required
def label_barcode_scan():
    """Scan shipping label barcode."""
    payload = request.get_json(silent=True) or {}
    barcode = (payload.get("barcode") or "").strip()
    if not barcode:
        return ("", 400)

    order_id, order_data = _load_order_for_barcode(barcode)
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

    # Store last label scan in session for auto-packing
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
    """Page for scanning shipping labels."""
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
    """Display recent scan logs for debugging."""
    limit = request.args.get("limit", 20, type=int)
    scan_type = request.args.get("type")  # 'product', 'label', or None for all
    
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
