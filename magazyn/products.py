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

from . import services
from .forms import AddItemForm
from .auth import login_required
from .constants import ALL_SIZES

bp = Blueprint('products', __name__)



@bp.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
    form = AddItemForm()
    if form.validate_on_submit():
        name = form.name.data
        color = form.color.data
        sizes = ALL_SIZES
        quantities = {size: services._to_int(getattr(form, f'quantity_{size}').data or 0) for size in sizes}
        barcodes = {size: getattr(form, f'barcode_{size}').data or None for size in sizes}

        try:
            services.create_product(name, color, quantities, barcodes)
        except Exception as e:
            flash(f'B\u0142\u0105d podczas dodawania przedmiotu: {e}')
        return redirect(url_for('products.items'))

    return render_template('add_item.html', form=form)


@bp.route('/update_quantity/<int:product_id>/<size>', methods=['POST'])
@login_required
def update_quantity(product_id, size):
    action = request.form['action']
    try:
        services.update_quantity(product_id, size, action)
    except Exception as e:
        flash(f'B\u0142\u0105d podczas aktualizacji ilo\u015bci: {e}')
    return redirect(url_for('products.items'))


@bp.route('/delete_item/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    try:
        deleted = services.delete_product(item_id)
    except Exception as e:
        flash(f'B\u0142ąd podczas usuwania przedmiotu: {e}')
        return redirect(url_for('products.items'))
    if not deleted:
        flash('Nie znaleziono produktu o podanym identyfikatorze')
        abort(404)
    flash('Przedmiot został usunięty')
    return redirect(url_for('products.items'))


@bp.route('/edit_item/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_item(product_id):
    if request.method == 'POST':
        name = request.form['name']
        color = request.form['color']
        sizes = ALL_SIZES
        quantities = {size: services._to_int(request.form.get(f'quantity_{size}', 0)) for size in sizes}
        barcodes = {size: request.form.get(f'barcode_{size}') or None for size in sizes}
        try:
            updated = services.update_product(product_id, name, color, quantities, barcodes)
        except Exception as e:
            flash(f'B\u0142ąd podczas aktualizacji przedmiotu: {e}')
            return redirect(url_for('products.items'))
        if not updated:
            flash('Nie znaleziono produktu o podanym identyfikatorze')
            abort(404)
        flash('Przedmiot został zaktualizowany')
        return redirect(url_for('products.items'))

    product, product_sizes = services.get_product_details(product_id)
    if not product:
        flash('Nie znaleziono produktu o podanym identyfikatorze')
        abort(404)
    return render_template('edit_item.html', product=product, product_sizes=product_sizes)


@bp.route('/items')
@login_required
def items():
    result = services.list_products()
    return render_template('items.html', products=result)


@bp.route('/barcode_scan', methods=['POST'])
@login_required
def barcode_scan():
    data = request.get_json(silent=True) or {}
    barcode = (data.get('barcode') or '').strip()
    if not barcode:
        return ('', 400)
    result = services.find_by_barcode(barcode)
    if result:
        flash(f'Znaleziono produkt: {result["name"]}')
        return jsonify(result)
    flash('Nie znaleziono produktu o podanym kodzie kreskowym')
    return ('', 400)


@bp.route('/scan_barcode')
@login_required
def barcode_scan_page():
    next_url = request.args.get('next', url_for('products.items'))
    return render_template('scan_barcode.html', next=next_url)


@bp.route('/export_products')
@login_required
def export_products():
    rows = services.export_rows()
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
                services.import_from_dataframe(df)
            except Exception as e:
                flash(f'B\u0142\u0105d podczas importowania produkt\u00f3w: {e}')
        return redirect(url_for('products.items'))
    return render_template('import_products.html')


@bp.route('/import_invoice', methods=['GET', 'POST'])
@login_required
def import_invoice():
    if request.method == 'POST':
        file = request.files.get('file')
        if file:
            try:
                data = file.read()
                filename = file.filename or ''
                ext = filename.rsplit('.', 1)[-1].lower()
                pdf_path = None
                if ext in {'xlsx', 'xls'}:
                    df = pd.read_excel(io.BytesIO(data))
                elif ext == 'pdf':
                    df = services._parse_pdf(io.BytesIO(data))
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                    tmp.write(data)
                    tmp.close()
                    pdf_path = tmp.name
                else:
                    raise ValueError('Nieobsługiwany format pliku')

                rows = df.to_dict(orient='records')
                session['invoice_rows'] = rows
                if pdf_path:
                    session['invoice_pdf'] = pdf_path
                else:
                    session.pop('invoice_pdf', None)
                return render_template('review_invoice.html', rows=rows, pdf_url=url_for('products.invoice_pdf') if pdf_path else None)
            except Exception as e:
                flash(f'Błąd podczas importu faktury: {e}')
                return redirect(url_for('products.items'))
        return redirect(url_for('products.items'))
    return render_template('import_invoice.html')


@bp.route('/invoice_pdf')
@login_required
def invoice_pdf():
    path = session.get('invoice_pdf')
    if path and os.path.exists(path):
        return send_file(path)
    abort(404)


@bp.route('/confirm_invoice', methods=['POST'])
@login_required
def confirm_invoice():
    rows = session.get('invoice_rows') or []
    confirmed = []
    for idx, base in enumerate(rows):
        if not request.form.get(f'accept_{idx}'):
            continue
        confirmed.append({
            'Nazwa': request.form.get(f'name_{idx}', base.get('Nazwa')),
            'Kolor': request.form.get(f'color_{idx}', base.get('Kolor')),
            'Rozmiar': request.form.get(f'size_{idx}', base.get('Rozmiar')),
            'Ilość': request.form.get(f'quantity_{idx}', base.get('Ilość')),
            'Cena': request.form.get(f'price_{idx}', base.get('Cena')),
            'Barcode': request.form.get(f'barcode_{idx}', base.get('Barcode')),
        })
    if confirmed:
        try:
            services.import_invoice_rows(confirmed)
            flash('Zaimportowano fakturę')
        except Exception as e:
            flash(f'Błąd podczas importu faktury: {e}')
    pdf_path = session.pop('invoice_pdf', None)
    if pdf_path:
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    session.pop('invoice_rows', None)
    return redirect(url_for('products.items'))


@bp.route('/deliveries', methods=['GET', 'POST'])
@login_required
def add_delivery():
    if request.method == 'POST':
        ids = request.form.getlist('product_id')
        sizes = request.form.getlist('size')
        quantities = request.form.getlist('quantity')
        prices = request.form.getlist('price')
        for pid, sz, qty, pr in zip(ids, sizes, quantities, prices):
            try:
                services.record_delivery(
                    int(pid), sz, services._to_int(qty), services._to_float(pr)
                )
            except Exception as e:
                flash(f'Błąd podczas dodawania dostawy: {e}')
        flash('Dodano dostawę')
        return redirect(url_for('products.items'))
    products = services.get_products_for_delivery()
    return render_template('add_delivery.html', products=products)

