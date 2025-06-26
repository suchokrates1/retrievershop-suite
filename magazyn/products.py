from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    jsonify,
    session,
    after_this_request,
)
import pandas as pd
import tempfile
import os

from .db import get_session, record_purchase, consume_stock
from .models import Product, ProductSize
from .forms import AddItemForm
from .auth import login_required
from . import print_agent

bp = Blueprint('products', __name__)



@bp.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
    form = AddItemForm()
    if form.validate_on_submit():
        name = form.name.data
        color = form.color.data
        sizes = ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']
        quantities = {size: int(getattr(form, f'quantity_{size}').data or 0) for size in sizes}
        barcodes = {size: getattr(form, f'barcode_{size}').data or None for size in sizes}

        try:
            with get_session() as db:
                product = Product(name=name, color=color)
                db.add(product)
                db.flush()
                for size, quantity in quantities.items():
                    db.add(
                        ProductSize(
                            product_id=product.id,
                            size=size,
                            quantity=quantity,
                            barcode=barcodes[size],
                        )
                    )
        except Exception as e:
            flash(f'B\u0142\u0105d podczas dodawania przedmiotu: {e}')
        return redirect(url_for('products.items'))

    return render_template('add_item.html', form=form)


@bp.route('/update_quantity/<int:product_id>/<size>', methods=['POST'])
@login_required
def update_quantity(product_id, size):
    action = request.form['action']
    try:
        with get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=product_id, size=size).first()
            if ps:
                if action == 'increase':
                    ps.quantity += 1
                elif action == 'decrease' and ps.quantity > 0:
                    consume_stock(product_id, size, 1)
    except Exception as e:
        flash(f'B\u0142\u0105d podczas aktualizacji ilo\u015bci: {e}')
    return redirect(url_for('products.items'))


@bp.route('/delete_item/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    try:
        with get_session() as db:
            db.query(ProductSize).filter_by(product_id=item_id).delete()
            db.query(Product).filter_by(id=item_id).delete()
        flash('Przedmiot został usunięty')
    except Exception as e:
        flash(f'B\u0142\u0105d podczas usuwania przedmiotu: {e}')
    return redirect(url_for('products.items'))


@bp.route('/edit_item/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_item(product_id):
    with get_session() as db:
        if request.method == 'POST':
            name = request.form['name']
            color = request.form['color']
            sizes = ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']
            quantities = {size: int(request.form.get(f'quantity_{size}', 0)) for size in sizes}
            barcodes = {size: request.form.get(f'barcode_{size}') or None for size in sizes}
            try:
                product = db.query(Product).filter_by(id=product_id).first()
                if product:
                    product.name = name
                    product.color = color
                for size, quantity in quantities.items():
                    ps = db.query(ProductSize).filter_by(product_id=product_id, size=size).first()
                    if ps:
                        ps.quantity = quantity
                        ps.barcode = barcodes[size]
                    else:
                        db.add(ProductSize(product_id=product_id, size=size, quantity=quantity, barcode=barcodes[size]))
                flash('Przedmiot został zaktualizowany')
            except Exception as e:
                flash(f'B\u0142\u0105d podczas aktualizacji przedmiotu: {e}')
            return redirect(url_for('products.items'))
        row = db.query(Product).filter_by(id=product_id).first()
        product = None
        if row:
            product = {
                'id': row.id,
                'name': row.name,
                'color': row.color,
            }
        sizes_rows = db.query(ProductSize).filter_by(product_id=product_id).all()
        all_sizes = ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']
        product_sizes = {size: {'quantity': 0, 'barcode': ''} for size in all_sizes}
        for s in sizes_rows:
            product_sizes[s.size] = {
                'quantity': s.quantity,
                'barcode': s.barcode or ''
            }
    return render_template('edit_item.html', product=product, product_sizes=product_sizes)


@bp.route('/items')
@login_required
def items():
    with get_session() as db:
        products = db.query(Product).all()
        result = []
        for p in products:
            sizes = {s.size: s.quantity for s in p.sizes}
            result.append({'id': p.id, 'name': p.name, 'color': p.color, 'sizes': sizes})
    return render_template('items.html', products=result)


@bp.route('/barcode_scan', methods=['POST'])
@login_required
def barcode_scan():
    data = request.get_json()
    barcode = data.get('barcode')
    if barcode:
        with get_session() as db:
            row = (
                db.query(Product.name, Product.color, ProductSize.size)
                .join(ProductSize)
                .filter(ProductSize.barcode == barcode)
                .first()
            )
            if row:
                name, color, size = row
                result = {"name": name, "color": color, "size": size}
            else:
                result = None
        if result:
            flash(f'Znaleziono produkt: {result["name"]}')
            return jsonify(result)
        else:
            flash('Nie znaleziono produktu o podanym kodzie kreskowym')
    return ('', 204)


@bp.route('/scan_barcode')
@login_required
def barcode_scan_page():
    return render_template('scan_barcode.html')


@bp.route('/export_products')
@login_required
def export_products():
    with get_session() as db:
        rows = (
            db.query(Product.name, Product.color, ProductSize.barcode, ProductSize.size, ProductSize.quantity)
            .join(ProductSize, Product.id == ProductSize.product_id, isouter=True)
            .all()
        )
    data = []
    for row in rows:
        data.append({
            'Nazwa': row[0],
            'Kolor': row[1],
            'Barcode': row[2],
            'Rozmiar': row[3],
            'Ilo\u015b\u0107': row[4],
        })
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

    return send_file(tmp.name, as_attachment=True, download_name='products_export.xlsx')


@bp.route('/import_products', methods=['GET', 'POST'])
@login_required
def import_products():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            try:
                df = pd.read_excel(file)
                with get_session() as db:
                    for _, row in df.iterrows():
                        name = row['Nazwa']
                        color = row['Kolor']
                        product = db.query(Product).filter_by(name=name, color=color).first()
                        if not product:
                            product = Product(name=name, color=color)
                            db.add(product)
                            db.flush()
                        for size in ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']:
                            quantity = row.get(f'Ilo\u015b\u0107 ({size})', 0)
                            size_barcode = row.get(f'Barcode ({size})')
                            ps = db.query(ProductSize).filter_by(product_id=product.id, size=size).first()
                            if not ps:
                                db.add(ProductSize(product_id=product.id, size=size, quantity=quantity, barcode=size_barcode))
                            else:
                                ps.quantity = quantity
                                ps.barcode = size_barcode
            except Exception as e:
                flash(f'B\u0142\u0105d podczas importowania produkt\u00f3w: {e}')
        return redirect(url_for('products.items'))
    return render_template('import_products.html')


@bp.route('/deliveries', methods=['GET', 'POST'])
@login_required
def add_delivery():
    if request.method == 'POST':
        product_id = int(request.form['product_id'])
        size = request.form['size']
        quantity = int(request.form['quantity'])
        price = float(request.form['price'])
        record_purchase(product_id, size, quantity, price)
        flash('Dodano dostawę')
        return redirect(url_for('products.items'))
    with get_session() as db:
        products = db.query(Product.id, Product.name, Product.color).all()
    return render_template('add_delivery.html', products=products)

