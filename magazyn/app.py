from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
import os
import pandas as pd
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key')
DB_PATH = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tworzenie tabeli użytkowników
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # Tworzenie tabeli produktów z kolumną barcode
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            color TEXT,
            barcode TEXT UNIQUE  -- Dodano kolumnę kodu kreskowego
        )
    ''')

    # Tworzenie tabeli rozmiarów produktów
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS product_sizes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            size TEXT CHECK(size IN ('XS', 'S', 'M', 'L', 'XL', 'Uniwersalny')) NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products (id),
            UNIQUE(product_id, size)
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_product_id ON product_sizes (product_id);
    ''')

    conn.commit()
    conn.close()

def register_default_user():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username = 'admin'")
    hashed_password = generate_password_hash('admin123', method='pbkdf2:sha256', salt_length=16)
    cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('admin', hashed_password))
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@login_required
def home():
    username = session['username']
    return render_template('home.html', username=username)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['username'] = username
            return redirect(url_for('home'))
        else:
            flash("Niepoprawna nazwa użytkownika lub hasło")
        return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
    if request.method == 'POST':
        name = request.form['name']
        color = request.form['color']
        barcode = request.form.get('barcode')  # Pobranie kodu kreskowego z formularza
        sizes = ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']
        quantities = {size: int(request.form.get(f'quantity_{size}', 0)) for size in sizes}
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("INSERT INTO products (name, color, barcode) VALUES (?, ?, ?)", (name, color, barcode))
            product_id = cursor.lastrowid

            for size, quantity in quantities.items():
                cursor.execute("INSERT INTO product_sizes (product_id, size, quantity) VALUES (?, ?, ?)", (product_id, size, quantity))

            conn.commit()
        except sqlite3.Error as e:
            flash(f'Błąd podczas dodawania przedmiotu: {e}')
        finally:
            conn.close()

        return redirect(url_for('items'))

    return render_template('add_item.html')  # formularz dodawania nowego przedmiotu
    
@app.route('/update_quantity/<int:product_id>/<size>', methods=['POST'])
@login_required
def update_quantity(product_id, size):
    action = request.form['action']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Pobranie obecnej ilości dla danego rozmiaru
        cursor.execute('''
            SELECT quantity FROM product_sizes
            WHERE product_id = ? AND size = ?
        ''', (product_id, size))
        
        result = cursor.fetchone()
        
        if result:
            current_quantity = result['quantity']
            
            # Zwiększenie lub zmniejszenie ilości
            if action == 'increase':
                new_quantity = current_quantity + 1
            elif action == 'decrease' and current_quantity > 0:
                new_quantity = current_quantity - 1
            else:
                new_quantity = current_quantity
            
            # Aktualizacja ilości w tabeli
            cursor.execute('''
                UPDATE product_sizes
                SET quantity = ?
                WHERE product_id = ? AND size = ?
            ''', (new_quantity, product_id, size))
            conn.commit()
    except sqlite3.Error as e:
        flash(f'Błąd podczas aktualizacji ilości: {e}')
    finally:
        conn.close()
    
    return redirect(url_for('items'))  # Powrót do widoku produktów

@app.route('/delete_item/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Usuń wszystkie rozmiary powiązane z produktem w tabeli product_sizes
        cursor.execute("DELETE FROM product_sizes WHERE product_id = ?", (item_id,))
        
        # Usuń produkt z tabeli products
        cursor.execute("DELETE FROM products WHERE id = ?", (item_id,))
        
        conn.commit()
        flash('Przedmiot został usunięty')
    except sqlite3.Error as e:
        flash(f'Błąd podczas usuwania przedmiotu: {e}')
    finally:
        conn.close()

    return redirect(url_for('items'))

@app.route('/edit_item/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_item(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        color = request.form['color']
        barcode = request.form.get('barcode')  # Pobranie kodu kreskowego z formularza
        sizes = ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']
        quantities = {size: int(request.form.get(f'quantity_{size}', 0)) for size in sizes}

        try:
            cursor.execute("UPDATE products SET name = ?, color = ?, barcode = ? WHERE id = ?", (name, color, barcode, product_id))
            
            for size, quantity in quantities.items():
                cursor.execute("UPDATE product_sizes SET quantity = ? WHERE product_id = ? AND size = ?", (quantity, product_id, size))

            conn.commit()
            flash('Przedmiot został zaktualizowany')
        except sqlite3.Error as e:
            flash(f'Błąd podczas aktualizacji przedmiotu: {e}')
        finally:
            conn.close()

        return redirect(url_for('items'))

    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    
    cursor.execute("SELECT size, quantity FROM product_sizes WHERE product_id = ?", (product_id,))
    sizes = cursor.fetchall()
    product_sizes = {size['size']: size['quantity'] for size in sizes}

    conn.close()
    return render_template('edit_item.html', product=product, product_sizes=product_sizes)

@app.route('/items')
@login_required
def items():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT products.id, products.name, products.color, products.barcode, product_sizes.size, product_sizes.quantity
        FROM products
        LEFT JOIN product_sizes ON products.id = product_sizes.product_id
    ''')
    rows = cursor.fetchall()
    conn.close()
    
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

@app.route('/barcode_scan', methods=['POST'])
@login_required
def barcode_scan():
    data = request.get_json()
    barcode = data.get('barcode')

    if barcode:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE barcode = ?", (barcode,))
        product = cursor.fetchone()
        conn.close()

        if product:
            flash(f'Znaleziono produkt: {product["name"]}')
        else:
            flash('Nie znaleziono produktu o podanym kodzie kreskowym')

    return ('', 204)

@app.route('/scan_barcode')
@login_required
def barcode_scan_page():
    return render_template('scan_barcode.html')
    
@app.route('/export_products')
@login_required
def export_products():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT products.name, products.color, product_sizes.size, product_sizes.quantity
        FROM products
        LEFT JOIN product_sizes ON products.id = product_sizes.product_id
    ''')
    rows = cursor.fetchall()
    conn.close()

    data = []
    for row in rows:
        data.append({
            'Nazwa': row['name'],
            'Kolor': row['color'],
            'Rozmiar': row['size'],
            'Ilość': row['quantity']
        })

    df = pd.DataFrame(data)
    file_path = '/tmp/products_export.xlsx'
    df.to_excel(file_path, index=False)

    return send_file(file_path, as_attachment=True, download_name='products_export.xlsx')

@app.route('/import_products', methods=['GET', 'POST'])
@login_required
def import_products():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            try:
                df = pd.read_excel(file)
                conn = get_db_connection()
                cursor = conn.cursor()

                for _, row in df.iterrows():
                    name = row['Nazwa']
                    color = row['Kolor']
                    cursor.execute("INSERT OR IGNORE INTO products (name, color) VALUES (?, ?)", (name, color))
                    product_id = cursor.lastrowid if cursor.lastrowid else cursor.execute("SELECT id FROM products WHERE name = ? AND color = ?", (name, color)).fetchone()['id']

                    for size in ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']:
                        quantity = row.get(f'Ilość ({size})', 0)
                        cursor.execute("INSERT OR IGNORE INTO product_sizes (product_id, size, quantity) VALUES (?, ?, ?)", (product_id, size, quantity))
                        cursor.execute("UPDATE product_sizes SET quantity = ? WHERE product_id = ? AND size = ?", (quantity, product_id, size))

                conn.commit()
            except Exception as e:
                flash(f'Błąd podczas importowania produktów: {e}')
            finally:
                conn.close()

        return redirect(url_for('items'))

    return render_template('import_products.html')

if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        init_db()
    register_default_user()
    app.run(host='0.0.0.0', port=80, debug=os.environ.get('FLASK_ENV') == 'development')
