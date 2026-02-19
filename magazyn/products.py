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
from .domain.invoice_import import _parse_pdf, import_invoice_rows, parse_product_name_to_fields
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
from .models import ProductSize, Product, PurchaseBatch, OrderProduct, Order, AllegroOffer
from .parsing import parse_product_info
from sqlalchemy import desc, or_, func


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
        'lumen',
        'amor',
        'blossom',
        'neon',
        'reflective',
        'dogi',
        'adventure',
        'handy',
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
    if len(parts) < 4:  # Minimum: TL-SZ-series-size (kolor opcjonalny - moze byc uciety)
        return {}
    
    # Map TipTop series codes to full names
    series_map = {
        'frolin-prem': 'front line premium',
        'frolin': 'front line',
        'tropic': 'tropical',
        'tropi': 'tropical',
        'active': 'active',
        'outdoo': 'outdoor',
        'classic': 'classic',
        'comfort': 'comfort',
        'sport': 'sport',
        'lumen': 'lumen',
        'dogi': 'dogi',
        'advent': 'adventure',
        'blossom': 'blossom',
        'amor': 'amor',
        'neon': 'neon',
        'handy': 'handy',
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
        'LIM': 'limonkowy',
    }
    
    # Extract components: TL-SZ-{series...}-{size}-{color}
    # Series can be multi-part (frolin-prem) so we parse from the end
    # SKU moze byc uciety (brak kodu koloru) np. TL-OB-tropi-XXXL
    
    # Normalizacja rozmiarow
    _size_aliases = {'XXL': '2XL', 'XXXL': '3XL'}
    
    if len(parts) >= 5:
        # Pelny format: TL-SZ-series-size-color
        color_code = parts[-1]
        size = parts[-2]
        series_parts = parts[2:-2]
    elif len(parts) == 4:
        # Uciety format: TL-SZ-series-size (bez koloru)
        color_code = ''
        size = parts[-1]
        series_parts = parts[2:-1]
    else:
        return {}
    
    series_code = '-'.join(series_parts)
    
    # Resolve series name
    series_name = series_map.get(series_code, '')
    
    # Resolve color
    color_name = color_map.get(color_code.upper(), '') if color_code else ''
    
    # Normalizuj rozmiar
    size_upper = size.upper()
    size_normalized = _size_aliases.get(size_upper, size_upper)
    
    return {
        'series': series_name,
        'size': size_normalized,
        'color': color_name,
        'color_code': color_code.upper() if color_code else '',
    }


def _extract_category(name: str) -> str:
    """Extract product category from name (Szelki, Obroza, Smycz, Pas)."""
    if not name:
        return ""
    name_lower = name.lower()
    if "smycz" in name_lower:
        return "Smycz"
    if "pas" in name_lower and ("bezpiecz" in name_lower or "samochodow" in name_lower):
        return "Pas bezpieczeństwa"
    if "obroża" in name_lower or "obroza" in name_lower or "obrozy" in name_lower:
        return "Obroża"
    if "szelki" in name_lower or "szelek" in name_lower:
        return "Szelki"
    return ""


def _match_by_tiptop_sku(sku: str, ps_list, row_name: str = "") -> tuple:
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
    
    # Wyciagnij kategorie z nazwy na fakturze
    row_category = _extract_category(row_name)
    
    for ps in ps_list:
        ps_series = _extract_model_series(ps.name)
        ps_size = (ps.size or '').upper()
        ps_color = (ps.color or '').lower()
        ps_category = getattr(ps, 'category', '') or _extract_category(ps.name)
        
        # Kategoria musi sie zgadzac (Szelki != Obroza)
        if row_category and ps_category and row_category != ps_category:
            continue
        
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
    row_category = _extract_category(row_name)
    
    if not row_key_words:
        return None, None, None
    
    best_match = None
    best_score = 0
    
    for ps in ps_list:
        ps_color_lower = (ps.color or "").lower().strip()
        ps_size_upper = (ps.size or "").upper().strip()
        ps_series = _extract_model_series(ps.name)
        ps_category = getattr(ps, 'category', '') or _extract_category(ps.name)
        
        # Kategoria MUSI sie zgadzac (Szelki != Obroza != Smycz)
        if row_category and ps_category and row_category != ps_category:
            continue
        
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
                flash("Proszę wpisać niestandardowy kolor", "error")
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
            flash(f"Błąd podczas dodawania przedmiotu: {e}", "error")
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
        flash("Nie znaleziono produktu o podanym identyfikatorze", "error")
        abort(404)
    flash("Przedmiot został usunięty", "success")
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
            flash(f"Błąd podczas aktualizacji przedmiotu: {e}", "error")
            return redirect(url_for("products.items"))
        if not updated:
            flash("Nie znaleziono produktu o podanym identyfikatorze", "error")
            abort(404)
        flash("Przedmiot został zaktualizowany", "success")
        return redirect(url_for("products.items"))

    product, product_sizes = get_product_details(product_id)
    if not product:
        flash("Nie znaleziono produktu o podanym identyfikatorze", "error")
        abort(404)
    return render_template(
        "edit_item.html", product=product, product_sizes=product_sizes
    )


@bp.route("/api/product/<int:product_id>/history")
@login_required
def product_history_api(product_id):
    """API endpoint do lazy loadingu historii produktu (zamowienia/dostawy)."""
    from sqlalchemy import func
    history_type = request.args.get("type", "orders")  # orders | deliveries
    offset = request.args.get("offset", 0, type=int)
    limit = request.args.get("limit", 50, type=int)
    if limit > 200:
        limit = 200

    with get_session() as db:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return jsonify({"error": "not_found"}), 404

        if history_type == "deliveries":
            total = db.query(func.count(PurchaseBatch.id)).filter(PurchaseBatch.product_id == product_id).scalar()
            batches = (
                db.query(PurchaseBatch)
                .filter(PurchaseBatch.product_id == product_id)
                .order_by(desc(PurchaseBatch.purchase_date))
                .offset(offset)
                .limit(limit)
                .all()
            )
            items = [
                {
                    "size": pb.size,
                    "quantity": pb.quantity,
                    "remaining": pb.remaining_quantity if pb.remaining_quantity is not None else pb.quantity,
                    "price": float(pb.price),
                    "total_value": float(pb.quantity * pb.price),
                    "date": pb.purchase_date.strftime("%Y-%m-%d") if pb.purchase_date else None,
                    "invoice_number": pb.invoice_number,
                    "supplier": pb.supplier,
                }
                for pb in batches
            ]
            return jsonify({"items": items, "total": total, "offset": offset, "has_more": offset + limit < total})

        else:  # orders
            sorted_sizes = product.sizes
            size_ids = [ps.id for ps in sorted_sizes]
            all_eans = [ps.barcode for ps in sorted_sizes if ps.barcode]
            size_map_by_id = {ps.id: ps.size for ps in sorted_sizes}
            size_map_by_ean = {ps.barcode: ps.size for ps in sorted_sizes if ps.barcode}

            filters = []
            if size_ids:
                filters.append(OrderProduct.product_size_id.in_(size_ids))
            if all_eans:
                filters.append(OrderProduct.ean.in_(all_eans))

            if not filters:
                return jsonify({"items": [], "total": 0, "offset": offset, "has_more": False})

            total = db.query(func.count(OrderProduct.id)).filter(or_(*filters)).scalar()
            order_products = (
                db.query(OrderProduct)
                .filter(or_(*filters))
                .order_by(desc(OrderProduct.id))
                .offset(offset)
                .limit(limit)
                .all()
            )

            items = []
            for op in order_products:
                if op.order:
                    size = None
                    if op.product_size_id and op.product_size_id in size_map_by_id:
                        size = size_map_by_id[op.product_size_id]
                    elif op.ean and op.ean in size_map_by_ean:
                        size = size_map_by_ean[op.ean]
                    items.append({
                        "order_id": op.order_id,
                        "lp": op.order.lp if hasattr(op.order, 'lp') and op.order.lp else op.order_id,
                        "date": op.order.date_add,
                        "customer": op.order.customer_name,
                        "quantity": op.quantity,
                        "price": float(op.price_brutto) if op.price_brutto else None,
                        "size": size,
                    })

            return jsonify({"items": items, "total": total, "offset": offset, "has_more": offset + limit < total})


@bp.route("/product/<int:product_id>")
@login_required
def product_detail(product_id):
    """Readonly product detail view with order and delivery history."""
    from decimal import Decimal
    from sqlalchemy import func
    from .models import AllegroOffer
    
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
        
        # Get order history for all sizes (via product_size_id + EAN fallback)
        order_history = []
        size_ids = [ps.id for ps in sorted_sizes]
        
        # Buduj slownik rozmiarow do szybkiego mapowania
        size_map_by_id = {ps.id: ps.size for ps in sorted_sizes}
        size_map_by_ean = {ps.barcode: ps.size for ps in sorted_sizes if ps.barcode}
        
        # Oblicz total_sold bez limitu
        filters = []
        if size_ids:
            filters.append(OrderProduct.product_size_id.in_(size_ids))
        if all_eans:
            filters.append(OrderProduct.ean.in_(all_eans))
        
        total_sold = 0
        if filters:
            total_sold = (
                db.query(func.coalesce(func.sum(OrderProduct.quantity), 0))
                .filter(or_(*filters))
                .scalar()
            ) or 0
            
            order_products = (
                db.query(OrderProduct)
                .filter(or_(*filters))
                .order_by(desc(OrderProduct.id))
                .limit(50)
                .all()
            )
            
            for op in order_products:
                if op.order:
                    # Ustal rozmiar - najpierw po product_size_id, potem po EAN
                    size = None
                    if op.product_size_id and op.product_size_id in size_map_by_id:
                        size = size_map_by_id[op.product_size_id]
                    elif op.ean and op.ean in size_map_by_ean:
                        size = size_map_by_ean[op.ean]
                    
                    # Numer LP zamowienia
                    lp = op.order.lp if hasattr(op.order, 'lp') and op.order.lp else op.order_id
                    
                    order_history.append({
                        "order_id": op.order_id,
                        "lp": lp,
                        "external_order_id": op.order.external_order_id,
                        "date": op.order.date_add,
                        "customer": op.order.customer_name,
                        "platform": op.order.platform,
                        "quantity": op.quantity,
                        "price": op.price_brutto,
                        "ean": op.ean,
                        "size": size,
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
        # total_sold juz obliczone wyzej przez SQL (bez limitu 50)
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
        
        # Get Allegro offers linked to this product or its sizes
        size_ids = [s["id"] for s in sizes_data]
        allegro_offers = (
            db.query(AllegroOffer)
            .filter(
                (AllegroOffer.product_id == product_id) |
                (AllegroOffer.product_size_id.in_(size_ids))
            )
            .order_by(AllegroOffer.title)
            .all()
        )
        
        allegro_data = []
        for offer in allegro_offers:
            # Find matching size
            matched_size = None
            if offer.product_size_id:
                matched_size = next(
                    (s["size"] for s in sizes_data if s["id"] == offer.product_size_id),
                    None
                )
            allegro_data.append({
                "offer_id": offer.offer_id,
                "title": offer.title,
                "price": offer.price,
                "ean": offer.ean,
                "matched_size": matched_size,
                "publication_status": offer.publication_status,
            })
        
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
            allegro_offers=allegro_data,
        )


@bp.route("/items")
@login_required
def items():
    search = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    if per_page not in [25, 50, 100, 200]:
        per_page = 50
    
    result = list_products()
    
    # Filtrowanie po nazwie/kolorze/serii/kategorii
    if search:
        s = search.lower()
        result = [
            p for p in result
            if s in (p.get("category") or "").lower()
            or s in (p.get("series") or "").lower()
            or s in (p.get("color") or "").lower()
            or s in (p.get("brand") or "").lower()
            or s in (p.get("name") or "").lower()
        ]
    
    total = len(result)
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    
    start = (page - 1) * per_page
    paginated = result[start:start + per_page]
    
    return render_template(
        "items.html",
        products=paginated,
        search=search,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


# Kod skanowania przeniesiony do blueprints/scanning.py


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
                invoice_number = None
                supplier = None
                
                if ext in {"xlsx", "xls"}:
                    df = pd.read_excel(io.BytesIO(data))
                elif ext == "pdf":
                    df, invoice_number, supplier = _parse_pdf(io.BytesIO(data))
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
                        ps_id, match_name, match_type = _match_by_tiptop_sku(
                            sku, ps_list, row.get("Nazwa", "")
                        )
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
                session["invoice_number"] = invoice_number
                session["invoice_supplier"] = supplier
                if pdf_path:
                    session["invoice_pdf"] = pdf_path
                else:
                    session.pop("invoice_pdf", None)
                return render_template(
                    "review_invoice.html",
                    rows=rows,
                    invoice_number=invoice_number,
                    supplier=supplier,
                    pdf_url=(
                        url_for("products.invoice_pdf") if pdf_path else None
                    ),
                    product_sizes=ps_list,
                )
            except Exception as e:
                flash(f"Błąd podczas importu faktury: {e}", "error")
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
    invoice_number = session.get("invoice_number")
    supplier = session.get("invoice_supplier")
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
                        invoice_number=invoice_number,
                        supplier=supplier,
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
            import_invoice_rows(confirmed, invoice_number=invoice_number, supplier=supplier)
            flash("Zaimportowano fakture", "success")
        except Exception as e:
            flash(f"Blad podczas importu faktury: {e}", "error")
    pdf_path = session.pop("invoice_pdf", None)
    if pdf_path:
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    session.pop("invoice_rows", None)
    session.pop("invoice_number", None)
    session.pop("invoice_supplier", None)
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
