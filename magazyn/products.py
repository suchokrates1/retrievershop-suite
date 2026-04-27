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
from .models.products import ProductSize
from .services.invoice_matching import match_invoice_rows
from .services.product_detail import (
    build_product_detail_context,
    build_product_history_payload,
)
from .services.product_listing import build_items_context

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
    payload, status_code = build_product_history_payload(
        product_id,
        history_type=history_type,
        offset=offset,
        limit=limit,
    )
    return jsonify(payload), status_code


@bp.route("/product/<int:product_id>")
@login_required
def product_detail(product_id):
    """Readonly product detail view with order and delivery history."""
    context = build_product_detail_context(product_id)
    if context is None:
        abort(404)
    return render_template("product_detail.html", **context)


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

                rows, ps_list = match_invoice_rows(df.to_dict(orient="records"))
                
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
