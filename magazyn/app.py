from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
import os
import pandas as pd
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv, dotenv_values
from collections import OrderedDict
from pathlib import Path
from contextlib import contextmanager
import print_agent
from __init__ import DB_PATH

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / '.env'
EXAMPLE_PATH = ROOT_DIR / '.env.example'

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key')


def start_print_agent():
    """Initialize and start the background label printing agent."""
    try:
        print_agent.validate_env()
        print_agent.ensure_db_init()
        print_agent.start_agent_thread()
    except Exception as e:
        app.logger.error(f"Failed to start print agent: {e}")


start_print_agent()


def load_settings():
    """Return OrderedDict of settings based on .env.example order."""
    example = dotenv_values(EXAMPLE_PATH)
    current = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    values = OrderedDict()
    for key in example.keys():
        values[key] = current.get(key, example[key])
    return values


def write_env(values):
    """Rewrite .env using provided mapping preserving .env.example order."""
    order = list(dotenv_values(EXAMPLE_PATH).keys())
    with ENV_PATH.open("w") as f:
        for key in order:
            val = values.get(key, "")
            f.write(f"{key}={val}\n")


@app.before_first_request
def _init_db_if_missing():
    if os.path.isdir(DB_PATH):
        app.logger.error(
            f"Database path {DB_PATH} is a directory. Please fix the mount."
        )
        raise SystemExit(1)
    if not os.path.isfile(DB_PATH):
        init_db()
    register_default_user()



@contextmanager
def get_db_connection():
    """Yield a database connection using a context manager."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        yield conn

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
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

        # Tables used by the printing agent
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS printed_orders(
                order_id TEXT PRIMARY KEY,
                printed_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS label_queue(
                order_id TEXT,
                label_data TEXT,
                ext TEXT,
                last_order_data TEXT
            )
            """
        )

        conn.commit()

def register_default_user():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username='admin'")
        if cursor.fetchone() is None:
            hashed_password = generate_password_hash(
                "admin123", method="pbkdf2:sha256", salt_length=16
            )
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                ("admin", hashed_password),
            )
            conn.commit()

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
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
        
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
            flash(f'Błąd podczas dodawania przedmiotu: {e}')

        return redirect(url_for('items'))

    return render_template('add_item.html')  # formularz dodawania nowego przedmiotu
    
@app.route('/update_quantity/<int:product_id>/<size>', methods=['POST'])
@login_required
def update_quantity(product_id, size):
    action = request.form['action']
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

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

    return redirect(url_for('items'))  # Powrót do widoku produktów

@app.route('/delete_item/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Usuń wszystkie rozmiary powiązane z produktem w tabeli product_sizes
            cursor.execute("DELETE FROM product_sizes WHERE product_id = ?", (item_id,))

            # Usuń produkt z tabeli products
            cursor.execute("DELETE FROM products WHERE id = ?", (item_id,))

            conn.commit()
            flash('Przedmiot został usunięty')
    except sqlite3.Error as e:
        flash(f'Błąd podczas usuwania przedmiotu: {e}')

    return redirect(url_for('items'))

@app.route('/edit_item/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_item(product_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if request.method == 'POST':
            name = request.form['name']
            color = request.form['color']
            barcode = request.form.get('barcode')  # Pobranie kodu kreskowego z formularza
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
                flash('Przedmiot został zaktualizowany')
            except sqlite3.Error as e:
                flash(f'Błąd podczas aktualizacji przedmiotu: {e}')

            return redirect(url_for('items'))

        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        product = cursor.fetchone()

        cursor.execute(
            "SELECT size, quantity FROM product_sizes WHERE product_id = ?",
            (product_id,),
        )
        sizes = cursor.fetchall()
        product_sizes = {size['size']: size['quantity'] for size in sizes}

    return render_template('edit_item.html', product=product, product_sizes=product_sizes)

@app.route('/items')
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

@app.route('/barcode_scan', methods=['POST'])
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
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
        SELECT products.name, products.color, product_sizes.size, product_sizes.quantity
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
                with get_db_connection() as conn:
                    cursor = conn.cursor()

                    for _, row in df.iterrows():
                        name = row['Nazwa']
                        color = row['Kolor']
                        cursor.execute(
                            "INSERT OR IGNORE INTO products (name, color) VALUES (?, ?)",
                            (name, color),
                        )
                        product_id = (
                            cursor.lastrowid
                            if cursor.lastrowid
                            else cursor.execute(
                                "SELECT id FROM products WHERE name = ? AND color = ?",
                                (name, color),
                            ).fetchone()['id']
                        )

                        for size in ['XS', 'S', 'M', 'L', 'XL', 'Uniwersalny']:
                            quantity = row.get(f'Ilość ({size})', 0)
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
                flash(f'Błąd podczas importowania produktów: {e}')

        return redirect(url_for('items'))

    return render_template('import_products.html')


@app.route('/history')
@login_required
def print_history():
    printed = print_agent.load_printed_orders()
    queue = print_agent.load_queue()
    return render_template('history.html', printed=printed, queue=queue)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        updated = {key: request.form.get(key, "") for key in dotenv_values(EXAMPLE_PATH).keys()}
        write_env(updated)
        load_dotenv(override=True)
        print_agent.reload_env()
        flash('Zapisano ustawienia.')
        return redirect(url_for('settings'))
    values = load_settings()
    return render_template('settings.html', settings=values)


@app.route('/logs')
@login_required
def agent_logs():
    try:
        with open(print_agent.LOG_FILE, "r") as f:
            lines = f.readlines()[-200:]
        log_text = "<br>".join(line.rstrip() for line in lines[::-1])
    except Exception as e:
        log_text = f"Błąd czytania logów: {e}"
    return render_template("logs.html", logs=log_text)


@app.route('/testprint', methods=['GET', 'POST'])
@login_required
def test_print():
    message = None
    if request.method == 'POST':
        success = print_agent.print_test_page()
        message = 'Testowy wydruk wysłany.' if success else 'Błąd testowego wydruku.'
    return render_template('testprint.html', message=message)


@app.route('/test', methods=['GET', 'POST'])
@login_required
def test_message():
    msg = None
    if request.method == 'POST':
        if print_agent.last_order_data:
            print_agent.send_messenger_message(print_agent.last_order_data)
            msg = 'Testowa wiadomość została wysłana.'
        else:
            msg = 'Brak danych ostatniego zamówienia.'
    return render_template('test.html', message=msg)

if __name__ == '__main__':
    if os.path.isdir(DB_PATH):
        app.logger.error(
            f"Database path {DB_PATH} is a directory. Please fix the mount."
        )
        raise SystemExit(1)
    if not os.path.isfile(DB_PATH):
        init_db()
    register_default_user()
    debug = os.getenv("FLASK_DEBUG") == "1"
    app.run(host="0.0.0.0", port=80, debug=debug)
