import json
import sqlite3
import re

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    jsonify,
    after_this_request,
    abort,
    session,
    current_app,
    g,
)
import pandas as pd
import tempfile
import os
import io

from .db import get_session, record_purchase, sqlite_connect
from .domain.inventory import (
    export_rows,
    get_product_sizes,
    get_product_size_by_barcode,
    get_products_for_delivery,
    import_from_dataframe,
    record_delivery,
    update_quantity as inventory_update_quantity,
)
from .domain.invoice_import import _parse_pdf, import_invoice_rows
from .domain.products import (
    _to_decimal,
    _to_int,
    create_product,
    delete_product,
    find_by_barcode,
    get_product_details,
    list_products,
    update_product,
)
from .forms import AddItemForm
from .auth import login_required
from .constants import ALL_SIZES
from .models import PrintedOrder, ProductSize, Product, PurchaseBatch, OrderProduct, Order, OrderStatusLog, ScanLog
from .parsing import parse_product_info
from sqlalchemy import desc
import time


def _extract_model_series(name: str) -> str:
    """Extract model series name from product name (e.g. 'Front Line Premium', 'Tropical', 'Active')."""
    if not name:
        return ""
    name_lower = name.lower()
    
    # Known model series - order matters (longer/more specific first)
    model_series = [
        'front line premium',
        'front line',
        'tropical',
        'active',
        'outdoor',
        'classic',
        'comfort',
        'sport',
        'easy walk',
    ]
    
    for series in model_series:
        if series in name_lower:
            return series
    return ""


def _parse_tiptop_sku(sku: str) -> dict:
    """
    Parse TipTop SKU to extract series, size, and color.
    Format: TL-SZ-{series}-{size}-{color}
    Examples:
        TL-SZ-frolin-prem-XL-CZA -> {series: 'front line premium', size: 'XL', color: 'czarny'}
        TL-SZ-frolin-XL-CZA -> {series: 'front line', size: 'XL', color: 'czarny'}
        TL-SZ-tropic-M-TUR -> {series: 'tropical', size: 'M', color: 'turkusowy'}
    """
    if not sku or not sku.startswith('TL-'):
        return {}
    
    parts = sku.split('-')
    if len(parts) < 5:  # Minimum: TL-SZ-series-size-color
        return {}
    
    # Map TipTop series codes to full names
    series_map = {
        'frolin-prem': 'front line premium',
        'frolin': 'front line',
        'tropic': 'tropical',
        'active': 'active',
        'outdoo': 'outdoor',
        'classic': 'classic',
        'comfort': 'comfort',
        'sport': 'sport',
    }
    
    # Map TipTop color codes to Polish colors
    color_map = {
        'CZA': 'czarny',
        'CZE': 'czerwony',
        'BRA': 'brązowy',
        'ROZ': 'różowy',
        'POM': 'pomarańczowy',
        'TUR': 'turkusowy',
        'BIA': 'biały',
        'NIE': 'niebieski',
        'ZIE': 'zielony',
        'SZA': 'szary',
        'FIO': 'fioletowy',
        'ZOL': 'żółty',
    }
    
    # Extract components: TL-SZ-{series...}-{size}-{color}
    # Series can be multi-part (frolin-prem) so we parse from the end
    color_code = parts[-1]
    size = parts[-2]
    series_parts = parts[2:-2]  # Everything between TL-SZ- and size-color
    series_code = '-'.join(series_parts)
    
    # Resolve series name
    series_name = series_map.get(series_code, '')
    
    # Resolve color
    color_name = color_map.get(color_code.upper(), '')
    
    return {
        'series': series_name,
        'size': size.upper(),
        'color': color_name,
        'color_code': color_code.upper(),
    }


def _match_by_tiptop_sku(sku: str, ps_list) -> tuple:
    """
    Match product by parsing TipTop SKU and finding exact match.
    Returns (ps_id, display_name, match_type) or (None, None, None)
    """
    parsed = _parse_tiptop_sku(sku)
    if not parsed or not parsed.get('series'):
        return None, None, None
    
    target_series = parsed['series']
    target_size = parsed.get('size', '').upper()
    target_color = parsed.get('color', '').lower()
    
    for ps in ps_list:
        ps_series = _extract_model_series(ps.name)
        ps_size = (ps.size or '').upper()
        ps_color = (ps.color or '').lower()
        
        # Series must match exactly
        if ps_series != target_series:
            continue
        
        # Size must match exactly
        if ps_size != target_size:
            continue
        
        # Color must match (fuzzy - contains or starts with)
        if target_color and ps_color:
            if target_color not in ps_color and ps_color not in target_color:
                # Try first 4 chars (czarn/czarny, brazow/brązowy)
                if target_color[:4] != ps_color[:4]:
                    continue
        
        # Found exact match!
        return ps.ps_id, f"{ps.name} ({ps.color}) {ps.size}", 'sku'
    
    return None, None, None


def _normalize_name(name: str) -> set:
    """Extract key words from product name for fuzzy matching."""
    if not name:
        return set()
    # Convert to lowercase
    name = name.lower()
    # Remove common filler words that don't identify the product
    filler_words = {
        'dla', 'psa', 'psy', 'kota', 'kotów', 'szelki', 'smycz', 'obroża',
        'profesjonalne', 'profesjonalny', 'guard', 'pro', 'plus',
        'z', 'od', 'do', 'na', 'w', 'i', 'a', 'o', 'ze', 'bez',
        'odpinanym', 'odpinany', 'przodem', 'przód', 'tyłem', 'tył',
        'nowy', 'nowa', 'nowe', 'nowych', 'model', 'wersja', 'typ',
        'mały', 'mała', 'małe', 'duży', 'duża', 'duże', 'średni', 'średnia',
        'easy', 'walk',  # handled separately in series
    }
    # Extract words
    words = re.findall(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+', name)
    # Filter out filler words and short words
    key_words = {w for w in words if w not in filler_words and len(w) > 2}
    return key_words


def _fuzzy_match_product(row_name: str, row_color: str, row_size: str, ps_list) -> tuple:
    """
    Try to fuzzy match a product based on name similarity.
    Returns (ps_id, display_name, match_type) or (None, None, None)
    match_type: 'ean' for exact EAN match, 'fuzzy' for name-based match
    """
    if not row_name:
        return None, None, None
    
    row_color_lower = (row_color or "").lower().strip()
    row_size_upper = (row_size or "").upper().strip()
    row_key_words = _normalize_name(row_name)
    row_series = _extract_model_series(row_name)
    
    if not row_key_words:
        return None, None, None
    
    best_match = None
    best_score = 0
    
    for ps in ps_list:
        ps_color_lower = (ps.color or "").lower().strip()
        ps_size_upper = (ps.size or "").upper().strip()
        ps_series = _extract_model_series(ps.name)
        
        # Size must match exactly if provided
        if row_size_upper and ps_size_upper and row_size_upper != ps_size_upper:
            continue
        
        # Model series MUST match exactly if both have a series
        # "Front Line" != "Front Line Premium"
        if row_series and ps_series and row_series != ps_series:
            continue
        
        # Color should match (fuzzy - check if one contains the other)
        color_match = False
        if not row_color_lower or not ps_color_lower:
            color_match = True  # No color to compare
        elif row_color_lower in ps_color_lower or ps_color_lower in row_color_lower:
            color_match = True
        elif row_color_lower[:4] == ps_color_lower[:4]:  # First 4 chars match (turkus/turkusowe)
            color_match = True
        
        if not color_match:
            continue
        
        # Compare key words
        ps_key_words = _normalize_name(ps.name)
        if not ps_key_words:
            continue
        
        # Calculate similarity score - how many key words match
        common_words = row_key_words & ps_key_words
        if not common_words:
            continue
        
        # Score based on: matched words / total unique words
        total_words = len(row_key_words | ps_key_words)
        score = len(common_words) / total_words if total_words > 0 else 0
        
        # Big bonus for matching model series exactly
        if row_series and ps_series and row_series == ps_series:
            score += 0.5
        
        # Bonus for matching brand name
        if 'truelove' in row_key_words and 'truelove' in ps_key_words:
            score += 0.2
        
        # Extra bonus if size matches exactly
        if row_size_upper and row_size_upper == ps_size_upper:
            score += 0.3
        
        if score > best_score and score >= 0.5:  # Minimum 50% similarity (raised from 40%)
            best_score = score
            best_match = ps
    
    if best_match:
        return best_match.ps_id, f"{best_match.name} ({best_match.color}) {best_match.size}", 'fuzzy'
    
    return None, None, None

bp = Blueprint("products", __name__)


@bp.route("/add_item", methods=["GET", "POST"])
@login_required
def add_item():
    form = AddItemForm()
    if form.validate_on_submit():
        category = form.category.data
        brand = form.brand.data or "Truelove"
        series = form.series.data or None
        color = form.color.data
        
        # If user selected "Inny" (Other), use custom color field
        if color == "Inny":
            custom_color = form.custom_color.data
            if custom_color and custom_color.strip():
                color = custom_color.strip()
            else:
                flash("Proszę wpisać niestandardowy kolor")
                return render_template("add_item.html", form=form)
        
        sizes = ALL_SIZES
        quantities = {
            size: _to_int(getattr(form, f"quantity_{size}").data or 0)
            for size in sizes
        }
        barcodes = {
            size: getattr(form, f"barcode_{size}").data or None
            for size in sizes
        }

        try:
            create_product(category, brand, series, color, quantities, barcodes)
        except Exception as e:
            flash(f"Błąd podczas dodawania przedmiotu: {e}")
        return redirect(url_for("products.items"))

    return render_template("add_item.html", form=form)


@bp.route("/update_quantity/<int:product_id>/<size>", methods=["POST"])
@login_required
def update_quantity(product_id, size):
    action = request.form["action"]
    try:
        inventory_update_quantity(product_id, size, action)
    except Exception as e:
        flash(f"B\u0142\u0105d podczas aktualizacji ilo\u015bci: {e}")
    return redirect(url_for("products.items"))


@bp.route("/delete_item/<int:item_id>", methods=["POST"])
@login_required
def delete_item(item_id):
    try:
        deleted = delete_product(item_id)
    except Exception as e:
        flash(f"B\u0142ąd podczas usuwania przedmiotu: {e}")
        return redirect(url_for("products.items"))
    if not deleted:
        flash("Nie znaleziono produktu o podanym identyfikatorze")
        abort(404)
    flash("Przedmiot został usunięty")
    return redirect(url_for("products.items"))


@bp.route("/edit_item/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_item(product_id):
    if request.method == "POST":
        category = request.form["category"]
        brand = request.form.get("brand") or "Truelove"
        series = request.form.get("series") or None
        color = request.form["color"]
        sizes = ALL_SIZES
        quantities = {
            size: _to_int(request.form.get(f"quantity_{size}", 0))
            for size in sizes
        }
        barcodes = {
            size: request.form.get(f"barcode_{size}") or None for size in sizes
        }
        purchase_prices = {
            size: _to_decimal(request.form.get(f"purchase_price_{size}")) if request.form.get(f"purchase_price_{size}") else None
            for size in sizes
        }
        try:
            updated = update_product(
                product_id, category, brand, series, color, quantities, barcodes, purchase_prices
            )
        except Exception as e:
            flash(f"Błąd podczas aktualizacji przedmiotu: {e}")
            return redirect(url_for("products.items"))
        if not updated:
            flash("Nie znaleziono produktu o podanym identyfikatorze")
            abort(404)
        flash("Przedmiot został zaktualizowany")
        return redirect(url_for("products.items"))

    product, product_sizes = get_product_details(product_id)
    if not product:
        flash("Nie znaleziono produktu o podanym identyfikatorze")
        abort(404)
    return render_template(
        "edit_item.html", product=product, product_sizes=product_sizes
    )


@bp.route("/product/<int:product_id>")
@login_required
def product_detail(product_id):
    """Readonly product detail view with order and delivery history."""
    from decimal import Decimal
    from sqlalchemy import func
    
    with get_session() as db:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            abort(404)
        
        # Get product sizes with their barcodes (EANs), purchase prices and stock info
        # Sort sizes: S, M, L, XL, 2XL
        size_order = {"S": 1, "M": 2, "L": 3, "XL": 4, "2XL": 5}
        sorted_sizes = sorted(product.sizes, key=lambda ps: size_order.get(ps.size, 99))
        
        sizes_data = []
        all_eans = []
        for ps in sorted_sizes:
            # Get latest purchase price for this size
            latest_batch = (
                db.query(PurchaseBatch)
                .filter(
                    PurchaseBatch.product_id == product_id,
                    PurchaseBatch.size == ps.size
                )
                .order_by(desc(PurchaseBatch.purchase_date))
                .first()
            )
            latest_price = latest_batch.price if latest_batch else None
            
            # Calculate weighted average purchase price for this size
            batches_for_size = (
                db.query(PurchaseBatch)
                .filter(
                    PurchaseBatch.product_id == product_id,
                    PurchaseBatch.size == ps.size,
                )
                .all()
            )
            total_qty = sum(b.quantity for b in batches_for_size)
            total_value = sum(b.quantity * b.price for b in batches_for_size)
            avg_price = (total_value / total_qty) if total_qty > 0 else None
            
            # Get remaining stock from FIFO batches
            remaining_batches = (
                db.query(PurchaseBatch)
                .filter(
                    PurchaseBatch.product_id == product_id,
                    PurchaseBatch.size == ps.size,
                    PurchaseBatch.remaining_quantity > 0,
                )
                .order_by(PurchaseBatch.purchase_date.asc())
                .all()
            )
            fifo_remaining = sum(b.remaining_quantity or 0 for b in remaining_batches)
            
            sizes_data.append({
                "id": ps.id,
                "size": ps.size,
                "quantity": ps.quantity,
                "fifo_remaining": fifo_remaining,
                "barcode": ps.barcode,
                "purchase_price": latest_price,  # Latest price
                "avg_purchase_price": avg_price,  # Weighted average
            })
            if ps.barcode:
                all_eans.append(ps.barcode)
        
        # Get order history for all sizes (via EAN)
        order_history = []
        if all_eans:
            order_products = (
                db.query(OrderProduct)
                .filter(OrderProduct.ean.in_(all_eans))
                .order_by(desc(OrderProduct.id))
                .limit(50)
                .all()
            )
            
            for op in order_products:
                if op.order:
                    order_history.append({
                        "order_id": op.order_id,
                        "external_order_id": op.order.external_order_id,
                        "date": op.order.date_add,
                        "customer": op.order.customer_name,
                        "platform": op.order.platform,
                        "quantity": op.quantity,
                        "price": op.price_brutto,
                        "ean": op.ean,
                        "size": next((s["size"] for s in sizes_data if s["barcode"] == op.ean), None),
                    })
        
        # Get delivery history (purchase batches) with full details
        delivery_history = (
            db.query(PurchaseBatch)
            .filter(PurchaseBatch.product_id == product_id)
            .order_by(desc(PurchaseBatch.purchase_date))
            .limit(100)
            .all()
        )
        
        deliveries = [
            {
                "id": pb.id,
                "size": pb.size,
                "quantity": pb.quantity,
                "remaining": pb.remaining_quantity if pb.remaining_quantity is not None else pb.quantity,
                "price": pb.price,
                "total_value": pb.quantity * pb.price,
                "date": pb.purchase_date,
                "barcode": pb.barcode,
                "invoice_number": pb.invoice_number,
                "supplier": pb.supplier,
            }
            for pb in delivery_history
        ]
        
        # Calculate totals
        total_in_stock = sum(s["quantity"] for s in sizes_data)
        total_sold = sum(o["quantity"] for o in order_history)
        total_delivered = sum(d["quantity"] for d in deliveries)
        
        # Calculate overall average purchase price
        all_batches = (
            db.query(PurchaseBatch)
            .filter(PurchaseBatch.product_id == product_id)
            .all()
        )
        total_purchased_qty = sum(b.quantity for b in all_batches)
        total_purchased_value = sum(b.quantity * b.price for b in all_batches)
        avg_purchase_price = (
            (total_purchased_value / total_purchased_qty) 
            if total_purchased_qty > 0 else None
        )
        
        return render_template(
            "product_detail.html",
            product=product,
            sizes=sizes_data,
            order_history=order_history,
            delivery_history=deliveries,
            total_in_stock=total_in_stock,
            total_sold=total_sold,
            total_delivered=total_delivered,
            avg_purchase_price=avg_purchase_price,
        )


@bp.route("/items")
@login_required
def items():
    result = list_products()
    return render_template("items.html", products=result)


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


@bp.route("/barcode_scan", methods=["POST"])
@login_required
def barcode_scan():
    data = request.get_json(silent=True) or {}
    barcode = (data.get("barcode") or "").strip()
    if not barcode:
        return ("", 400)
    result = find_by_barcode(barcode)
    if result:
        # Log successful scan
        _log_scan('product', barcode, True, result)
        
        # Store last product scan in session for auto-packing
        session['last_product_scan'] = {
            'barcode': barcode,
            'product_size_id': result.get('product_size_id'),
            'timestamp': time.time()
        }
        
        # Check if we can auto-pack: recently scanned label + this product belongs to that order
        _check_and_auto_pack()
        
        flash(f'Znaleziono produkt: {result["name"]}')
        return jsonify(result)
    
    # Log failed scan
    _log_scan('product', barcode, False, error_message="Nie znaleziono produktu")
    flash("Nie znaleziono produktu o podanym kodzie kreskowym")
    return ("", 400)


@bp.route("/scan_barcode")
@login_required
def barcode_scan_page():
    next_url = request.args.get("next", url_for("products.items"))
    return render_template("scan_barcode.html", next=next_url)


def _parse_last_order_data(raw):
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
        return
    
    # Check if scanned product belongs to the scanned order
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
            return
        
        current_app.logger.info(f"Auto-pack: ✓ Produkt {product_size_id} należy do zamówienia {order_id}")
        
        # All conditions met - change status to "spakowano"
        new_status = OrderStatusLog(
            order_id=order_id,
            status="spakowano",
            notes="Automatycznie spakowano po zeskanowaniu etykiety i produktu"
        )
        db.add(new_status)
        db.commit()
        
        current_app.logger.info(f"✅ AUTO-PACK SUCCESS: Zamówienie {order_id} -> spakowano")
        
        # Clear session data to prevent duplicate packing
        session.pop('last_product_scan', None)
        session.pop('last_label_scan', None)
        
        flash(f'Spakowano', 'success')


def _load_order_for_barcode(barcode: str):
    matched_order_id = None
    order_data = None
    barcode = barcode.strip()

    with get_session() as session:
        direct = session.get(PrintedOrder, barcode)
        if direct:
            matched_order_id = direct.order_id
            order_data = _parse_last_order_data(direct.last_order_data)

        if not order_data:
            for po in session.query(PrintedOrder).all():
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


@bp.route("/label_scan", methods=["POST"])
@login_required
def label_barcode_scan():
    payload = request.get_json(silent=True) or {}
    barcode = (payload.get("barcode") or "").strip()
    if not barcode:
        return ("", 400)

    order_id, order_data = _load_order_for_barcode(barcode)
    if not order_data:
        # Log failed scan
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
    
    # Check if we can auto-pack: recently scanned product + it belongs to this order
    _check_and_auto_pack()

    # Get delivery method for better TTS
    delivery_method = order_data.get("shipping") or order_data.get("delivery_method") or ""
    courier_code = order_data.get("courier_code") or order_data.get("delivery_package_module") or ""

    response = {
        "order_id": order_id or order_data.get("order_id") or "",
        "package_ids": order_data.get("package_ids") or [],
        "products": products,
        "delivery_method": delivery_method,
        "courier_code": courier_code,
    }
    
    # Log successful scan
    _log_scan('label', barcode, True, response)
    
    return jsonify(response)


@bp.route("/scan_label")
@login_required
def label_scan_page():
    next_url = request.args.get("next", url_for("products.items"))
    return render_template(
        "scan_label.html",
        next=next_url,
        barcode_mode="label",
        barcode_endpoint=url_for("products.label_barcode_scan"),
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
    
    # If JSON requested
    if request.headers.get('Accept') == 'application/json':
        return jsonify(result)
    
    return render_template("scan_logs.html", logs=result)


@bp.route("/export_products")
@login_required
def export_products():
    rows = export_rows()
    data = []
    for row in rows:
        data.append(
            {
                "Nazwa": row[0],
                "Kolor": row[1],
                "Barcode": row[2],
                "Rozmiar": row[3],
                "Ilo\u015b\u0107": row[4],
            }
        )
    df = pd.DataFrame(data)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    df.to_excel(tmp.name, index=False)

    @after_this_request
    def remove_tmp(response):
        try:
            os.remove(tmp.name)
        except OSError:
            pass
        return response

    return send_file(
        tmp.name, as_attachment=True, download_name="products_export.xlsx"
    )


@bp.route("/import_products", methods=["GET", "POST"])
@login_required
def import_products():
    if request.method == "POST":
        file = request.files["file"]
        if file:
            try:
                df = pd.read_excel(file)
                import_from_dataframe(df)
            except Exception as e:
                flash(
                    f"B\u0142\u0105d podczas importowania produkt\u00f3w: {e}"
                )
        return redirect(url_for("products.items"))
    return render_template("import_products.html")


@bp.route("/import_invoice", methods=["GET", "POST"])
@login_required
def import_invoice():
    if request.method == "POST":
        file = request.files.get("file")
        if file:
            try:
                data = file.read()
                filename = file.filename or ""
                ext = filename.rsplit(".", 1)[-1].lower()
                pdf_path = None
                if ext in {"xlsx", "xls"}:
                    df = pd.read_excel(io.BytesIO(data))
                elif ext == "pdf":
                    df = _parse_pdf(io.BytesIO(data))
                    tmp = tempfile.NamedTemporaryFile(
                        delete=False, suffix=".pdf"
                    )
                    tmp.write(data)
                    tmp.close()
                    pdf_path = tmp.name
                else:
                    raise ValueError("Nieobsługiwany format pliku")

                rows = df.to_dict(orient="records")
                
                # Match products by EAN/barcode first, then TipTop SKU parsing, then fuzzy matching
                ps_list = get_product_sizes()
                barcode_map = {ps.barcode: ps for ps in ps_list if ps.barcode}
                
                for row in rows:
                    barcode = row.get("Barcode") or row.get("EAN") or ""
                    barcode = str(barcode).strip() if barcode else ""
                    sku = row.get("SKU") or ""
                    sku = str(sku).strip() if sku else ""
                    row["matched_ps_id"] = None
                    row["matched_name"] = None
                    row["match_type"] = None  # 'ean', 'sku', or 'fuzzy'
                    
                    # Priority 1: EAN match (most reliable)
                    if barcode and barcode in barcode_map:
                        ps = barcode_map[barcode]
                        row["matched_ps_id"] = ps.ps_id
                        row["matched_name"] = f"{ps.name} ({ps.color}) {ps.size}"
                        row["match_type"] = "ean"
                    # Priority 2: Parse TipTop SKU and match by series+size+color
                    elif sku:
                        ps_id, match_name, match_type = _match_by_tiptop_sku(sku, ps_list)
                        if ps_id:
                            row["matched_ps_id"] = ps_id
                            row["matched_name"] = match_name
                            row["match_type"] = match_type
                    
                    # Priority 3: Fuzzy name matching (if not already matched)
                    if not row["matched_ps_id"]:
                        ps_id, match_name, match_type = _fuzzy_match_product(
                            row.get("Nazwa", ""),
                            row.get("Kolor", ""),
                            row.get("Rozmiar", ""),
                            ps_list
                        )
                        if ps_id:
                            row["matched_ps_id"] = ps_id
                            row["matched_name"] = match_name
                            row["match_type"] = match_type
                
                session["invoice_rows"] = rows
                if pdf_path:
                    session["invoice_pdf"] = pdf_path
                else:
                    session.pop("invoice_pdf", None)
                return render_template(
                    "review_invoice.html",
                    rows=rows,
                    pdf_url=(
                        url_for("products.invoice_pdf") if pdf_path else None
                    ),
                    product_sizes=ps_list,
                )
            except Exception as e:
                flash(f"Błąd podczas importu faktury: {e}")
                return redirect(url_for("products.items"))
        return redirect(url_for("products.items"))
    return render_template("import_invoice.html")


@bp.route("/invoice_pdf")
@login_required
def invoice_pdf():
    path = session.get("invoice_pdf")
    if path and os.path.exists(path):
        return send_file(path)
    abort(404)


@bp.route("/confirm_invoice", methods=["POST"])
@login_required
def confirm_invoice():
    rows = session.get("invoice_rows") or []
    confirmed = []
    for idx, base in enumerate(rows):
        if not request.form.get(f"accept_{idx}"):
            continue
        ps_id = request.form.get(f"ps_id_{idx}")
        qty_val = request.form.get(f"quantity_{idx}", base.get("Ilość"))
        price_val = request.form.get(f"price_{idx}", base.get("Cena"))
        if ps_id:
            with get_session() as db:
                ps = (
                    db.query(ProductSize)
                    .filter_by(id=int(ps_id))
                    .first()
                )
                if ps:
                    record_purchase(
                        ps.product_id,
                        ps.size,
                        _to_int(qty_val),
                        _to_decimal(price_val),
                    )
            continue
        confirmed.append(
            {
                "Nazwa": request.form.get(f"name_{idx}", base.get("Nazwa")),
                "Kolor": request.form.get(f"color_{idx}", base.get("Kolor")),
                "Rozmiar": request.form.get(
                    f"size_{idx}", base.get("Rozmiar")
                ),
                "Ilość": qty_val,
                "Cena": price_val,
                "Barcode": request.form.get(
                    f"barcode_{idx}", base.get("Barcode")
                ),
            }
        )
    if confirmed:
        try:
            import_invoice_rows(confirmed)
            flash("Zaimportowano fakturę")
        except Exception as e:
            flash(f"Błąd podczas importu faktury: {e}")
    pdf_path = session.pop("invoice_pdf", None)
    if pdf_path:
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    session.pop("invoice_rows", None)
    return redirect(url_for("products.items"))


@bp.route("/deliveries", methods=["GET", "POST"])
@login_required
def add_delivery():
    if request.method == "POST":
        eans = request.form.getlist("ean")
        ids = request.form.getlist("product_id")
        sizes = request.form.getlist("size")
        quantities = request.form.getlist("quantity")
        prices = request.form.getlist("price")
        
        errors = []
        success_count = 0
        
        for ean, pid, sz, qty, pr in zip(eans, ids, sizes, quantities, prices):
            ean = ean.strip() if ean else ""
            pid = pid.strip() if pid else ""
            sz = sz.strip() if sz else ""
            
            try:
                # First try to match by EAN
                if ean:
                    with get_session() as db:
                        ps = db.query(ProductSize).filter(ProductSize.barcode == ean).first()
                        if ps:
                            # Found by EAN - use this product size
                            record_delivery(
                                ps.product_id, ps.size, _to_int(qty), _to_decimal(pr)
                            )
                            success_count += 1
                            continue
                        else:
                            errors.append(f"EAN {ean} nie znaleziony w magazynie")
                            continue
                
                # Fall back to product_id + size selection
                if pid and sz:
                    record_delivery(
                        int(pid), sz, _to_int(qty), _to_decimal(pr)
                    )
                    success_count += 1
                else:
                    errors.append("Brak EAN lub wyboru produktu/rozmiaru")
                    
            except Exception as e:
                errors.append(f"Błąd: {e}")
        
        if success_count > 0:
            flash(f"Dodano {success_count} pozycji dostawy", "success")
        for err in errors:
            flash(err, "error")
            
        return redirect(url_for("products.items"))
    products = get_products_for_delivery()
    return render_template("add_delivery.html", products=products)
