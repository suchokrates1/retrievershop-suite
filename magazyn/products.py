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
)
import pandas as pd
import tempfile
import os
import io
import logging

from .db import get_session, record_purchase
from .domain.inventory import (
    export_rows,
    get_product_sizes,
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
    get_product_details,
    update_product,
)
from .forms import AddItemForm
from .auth import login_required
from .constants import ALL_SIZES
from .models.allegro import AllegroOffer
from .models.orders import OrderProduct
from .models.products import Product, ProductSize, PurchaseBatch
from .services.product_matching import (
    _extract_category,  # noqa: F401 - publiczny helper kompatybilnosci
    _extract_model_series,  # noqa: F401 - publiczny helper kompatybilnosci
    _fuzzy_match_product,
    _match_by_tiptop_sku,
    _normalize_name,  # noqa: F401 - publiczny helper kompatybilnosci
    _parse_tiptop_sku,  # noqa: F401 - publiczny helper kompatybilnosci
)
from .services.product_listing import build_items_context
from sqlalchemy import desc, or_, func

bp = Blueprint("products", __name__)

logger = logging.getLogger(__name__)


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
        except Exception as exc:
            logger.exception("Blad podczas dodawania produktu")
            flash(f"Błąd podczas dodawania przedmiotu: {exc}", "error")
        return redirect(url_for("products.items"))

    return render_template("add_item.html", form=form)


@bp.route("/update_quantity/<int:product_id>/<size>", methods=["POST"])
@login_required
def update_quantity(product_id, size):
    action = request.form["action"]
    try:
        inventory_update_quantity(product_id, size, action)
    except Exception as exc:
        logger.exception("Blad podczas aktualizacji ilosci produktu")
        flash(f"B\u0142\u0105d podczas aktualizacji ilo\u015bci: {exc}")
    return redirect(url_for("products.items"))


@bp.route("/delete_item/<int:item_id>", methods=["POST"])
@login_required
def delete_item(item_id):
    try:
        deleted = delete_product(item_id)
    except Exception as exc:
        logger.exception("Blad podczas usuwania produktu")
        flash(f"B\u0142ąd podczas usuwania przedmiotu: {exc}")
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
        except Exception as exc:
            logger.exception("Blad podczas aktualizacji produktu")
            flash(f"Błąd podczas aktualizacji przedmiotu: {exc}", "error")
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
    context = build_items_context(search=search, page=page, per_page=per_page)
    return render_template("items.html", **context)


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
            except Exception as exc:
                logger.exception("Blad podczas importowania produktow")
                flash(
                    f"B\u0142\u0105d podczas importowania produkt\u00f3w: {exc}"
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
            except Exception as exc:
                logger.exception("Blad podczas importu faktury")
                flash(f"Błąd podczas importu faktury: {exc}", "error")
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
        except Exception as exc:
            logger.exception("Blad podczas potwierdzania faktury")
            flash(f"Blad podczas importu faktury: {exc}", "error")
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
                    
            except Exception as exc:
                logger.exception("Blad podczas dodawania dostawy")
                errors.append(f"Błąd: {exc}")
        
        if success_count > 0:
            flash(f"Dodano {success_count} pozycji dostawy", "success")
        for err in errors:
            flash(err, "error")
            
        return redirect(url_for("products.items"))
    products = get_products_for_delivery()
    return render_template("add_delivery.html", products=products)
