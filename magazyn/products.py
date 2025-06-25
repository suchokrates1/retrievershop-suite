from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    send_file, jsonify, session
)
import sqlite3
import pandas as pd

from .db import get_db_connection
from .auth import login_required
from . import print_agent

bp = Blueprint('products', __name__)



@bp.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
    if request.method == 'POST':
        name = request.form['name']
        color = request.form['color']
        barcode = request.form.get('barcode')
        sizes = ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']
        quantities = {size: int(request.form.get(f'quantity_{size}', 0)) for size in sizes}

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO products (name, color, barcode) VALUES (?, ?, ?)",
                    (name, color, barcode),
                )
                product_id = cursor.lastrowid
                for size, quantity in quantities.items():
                    cursor.execute(
                        "INSERT INTO product_sizes (product_id, size, quantity) VALUES (?, ?, ?)",
                        (product_id, size, quantity),
                    )
                conn.commit()
        except sqlite3.Error as e:
            flash(f'B\u0142\u0105d podczas dodawania przedmiotu: {e}')
        return redirect(url_for('products.items'))

    return render_template('add_item.html')


@bp.route('/update_quantity/<int:product_id>/<size>', methods=['POST'])
@login_required
def update_quantity(product_id, size):
    action = request.form['action']
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
            SELECT quantity FROM product_sizes
            WHERE product_id = ? AND size = ?
        ''', (product_id, size))
            result = cursor.fetchone()
            if result:
                current_quantity = result['quantity']
                if action == 'increase':
                    new_quantity = current_quantity + 1
                elif action == 'decrease' and current_quantity > 0:
                    new_quantity = current_quantity - 1
                else:
                    new_quantity = current_quantity
                cursor.execute(
                    '''
                    UPDATE product_sizes
                    SET quantity = ?
                    WHERE product_id = ? AND size = ?
                ''', (new_quantity, product_id, size))
                conn.commit()
    except sqlite3.Error as e:
        flash(f'B\u0142\u0105d podczas aktualizacji ilo\u015bci: {e}')
    return redirect(url_for('products.items'))


@bp.route('/delete_item/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM product_sizes WHERE product_id = ?", (item_id,))
            cursor.execute("DELETE FROM products WHERE id = ?", (item_id,))
            conn.commit()
            flash('Przedmiot zosta\u0142 usuni\u0119ty')
    except sqlite3.Error as e:
        flash(f'B\u0142\u0105d podczas usuwania przedmiotu: {e}')
    return redirect(url_for('products.items'))


@bp.route('/edit_item/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_item(product_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if request.method == 'POST':
            name = request.form['name']
            color = request.form['color']
            barcode = request.form.get('barcode')
            sizes = ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']
            quantities = {size: int(request.form.get(f'quantity_{size}', 0)) for size in sizes}
            try:
                cursor.execute(
                    "UPDATE products SET name = ?, color = ?, barcode = ? WHERE id = ?",
                    (name, color, barcode, product_id),
                )
                for size, quantity in quantities.items():
                    cursor.execute(
                        "UPDATE product_sizes SET quantity = ? WHERE product_id = ? AND size = ?",
                        (quantity, product_id, size),
                    )
                conn.commit()
                flash('Przedmiot zosta\u0142 zaktualizowany')
            except sqlite3.Error as e:
                flash(f'B\u0142\u0105d podczas aktualizacji przedmiotu: {e}')
            return redirect(url_for('products.items'))
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        product = cursor.fetchone()
        cursor.execute(
            "SELECT size, quantity FROM product_sizes WHERE product_id = ?",
            (product_id,),
        )
        sizes = cursor.fetchall()
        product_sizes = {size['size']: size['quantity'] for size in sizes}
    return render_template('edit_item.html', product=product, product_sizes=product_sizes)


@bp.route('/items')
@login_required
def items():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
        SELECT products.id, products.name, products.color, products.barcode, product_sizes.size, product_sizes.quantity
        FROM products
        LEFT JOIN product_sizes ON products.id = product_sizes.product_id
    '''
        )
        rows = cursor.fetchall()
    products_data = {}
    for row in rows:
        product_id = row['id']
        if product_id not in products_data:
            products_data[product_id] = {
                'id': product_id,
                'name': row['name'],
                'color': row['color'],
                'barcode': row['barcode'],
                'sizes': {}
            }
        products_data[product_id]['sizes'][row['size']] = row['quantity']
    return render_template('items.html', products=products_data.values())


@bp.route('/barcode_scan', methods=['POST'])
@login_required
def barcode_scan():
    data = request.get_json()
    barcode = data.get('barcode')
    if barcode:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE barcode = ?", (barcode,))
            product = cursor.fetchone()
        if product:
            flash(f'Znaleziono produkt: {product["name"]}')
            return jsonify({'name': product['name']})
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
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
        SELECT products.name, products.color, products.barcode, product_sizes.size, product_sizes.quantity
        FROM products
        LEFT JOIN product_sizes ON products.id = product_sizes.product_id
    '''
        )
        rows = cursor.fetchall()
    data = []
    for row in rows:
        data.append({
            'Nazwa': row['name'],
            'Kolor': row['color'],
            'Barcode': row['barcode'],
            'Rozmiar': row['size'],
            'Ilo\u015b\u0107': row['quantity']
        })
    df = pd.DataFrame(data)
    file_path = '/tmp/products_export.xlsx'
    df.to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True, download_name='products_export.xlsx')


@bp.route('/import_products', methods=['GET', 'POST'])
@login_required
def import_products():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            try:
                df = pd.read_excel(file)
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    for _, row in df.iterrows():
                        name = row['Nazwa']
                        color = row['Kolor']
                        barcode = row.get('Barcode')
                        cursor.execute(
                            "INSERT OR IGNORE INTO products (name, color, barcode) VALUES (?, ?, ?)",
                            (name, color, barcode),
                        )
                        product_id = (
                            cursor.lastrowid
                            if cursor.lastrowid
                            else cursor.execute(
                                "SELECT id FROM products WHERE name = ? AND color = ?",
                                (name, color),
                            ).fetchone()['id']
                        )
                        if not cursor.lastrowid:
                            cursor.execute(
                                "UPDATE products SET barcode = ? WHERE id = ?",
                                (barcode, product_id),
                            )
                        for size in ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']:
                            quantity = row.get(f'Ilo\u015b\u0107 ({size})', 0)
                            cursor.execute(
                                "INSERT OR IGNORE INTO product_sizes (product_id, size, quantity) VALUES (?, ?, ?)",
                                (product_id, size, quantity),
                            )
                            cursor.execute(
                                "UPDATE product_sizes SET quantity = ? WHERE product_id = ? AND size = ?",
                                (quantity, product_id, size),
                            )
                    conn.commit()
            except Exception as e:
                flash(f'B\u0142\u0105d podczas importowania produkt\u00f3w: {e}')
        return redirect(url_for('products.items'))
    return render_template('import_products.html')

