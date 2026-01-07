import json
import sqlite3

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

from .db import get_session, record_purchase, sqlite_connect
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
    find_by_barcode,
    get_product_details,
    list_products,
    update_product,
)
from .forms import AddItemForm
from .auth import login_required
from .constants import ALL_SIZES
from .models import PrintedOrder, ProductSize, Product, PurchaseBatch, OrderProduct, Order
from .parsing import parse_product_info
from sqlalchemy import desc

bp = Blueprint("products", __name__)


@bp.route("/add_item", methods=["GET", "POST"])
@login_required
def add_item():
    form = AddItemForm()
    if form.validate_on_submit():
        name = form.name.data
        color = form.color.data
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
            create_product(name, color, quantities, barcodes)
        except Exception as e:
            flash(f"B\u0142\u0105d podczas dodawania przedmiotu: {e}")
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
        name = request.form["name"]
        color = request.form["color"]
        sizes = ALL_SIZES
        quantities = {
            size: _to_int(request.form.get(f"quantity_{size}", 0))
            for size in sizes
        }
        barcodes = {
            size: request.form.get(f"barcode_{size}") or None for size in sizes
        }
        try:
            updated = update_product(
                product_id, name, color, quantities, barcodes
            )
        except Exception as e:
            flash(f"B\u0142ąd podczas aktualizacji przedmiotu: {e}")
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
    with get_session() as db:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            abort(404)
        
        # Get product sizes with their barcodes (EANs)
        sizes_data = []
        all_eans = []
        for ps in product.sizes:
            sizes_data.append({
                "id": ps.id,
                "size": ps.size,
                "quantity": ps.quantity,
                "barcode": ps.barcode,
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
        
        # Get delivery history (purchase batches)
        delivery_history = (
            db.query(PurchaseBatch)
            .filter(PurchaseBatch.product_id == product_id)
            .order_by(desc(PurchaseBatch.purchase_date))
            .limit(50)
            .all()
        )
        
        deliveries = [
            {
                "id": pb.id,
                "size": pb.size,
                "quantity": pb.quantity,
                "price": pb.price,
                "date": pb.purchase_date,
            }
            for pb in delivery_history
        ]
        
        # Calculate totals
        total_in_stock = sum(s["quantity"] for s in sizes_data)
        total_sold = sum(o["quantity"] for o in order_history)
        total_delivered = sum(d["quantity"] for d in deliveries)
        
        return render_template(
            "product_detail.html",
            product=product,
            sizes=sizes_data,
            order_history=order_history,
            delivery_history=deliveries,
            total_in_stock=total_in_stock,
            total_sold=total_sold,
            total_delivered=total_delivered,
        )


@bp.route("/items")
@login_required
def items():
    result = list_products()
    return render_template("items.html", products=result)


@bp.route("/barcode_scan", methods=["POST"])
@login_required
def barcode_scan():
    data = request.get_json(silent=True) or {}
    barcode = (data.get("barcode") or "").strip()
    if not barcode:
        return ("", 400)
    result = find_by_barcode(barcode)
    if result:
        flash(f'Znaleziono produkt: {result["name"]}')
        return jsonify(result)
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

    response = {
        "order_id": order_id or order_data.get("order_id") or "",
        "package_ids": order_data.get("package_ids") or [],
        "products": products,
    }
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
                session["invoice_rows"] = rows
                if pdf_path:
                    session["invoice_pdf"] = pdf_path
                else:
                    session.pop("invoice_pdf", None)
                ps_list = get_product_sizes()
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
