"""
Główny moduł aplikacji Flask - podstawowe widoki i routing.
Wydzielone funkcjonalności:
- discussions.py - dyskusje Allegro
- template_filters.py - filtry Jinja2
"""
from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    has_request_context,
    has_app_context,
    make_response,
    jsonify,
)
from datetime import datetime
import os
import hmac
from werkzeug.security import check_password_hash
from collections import OrderedDict
from typing import Optional
import zipfile
from io import BytesIO
from pathlib import Path

from .models import User, Thread, Product, ProductSize, Order, OrderProduct, PurchaseBatch, AllegroOffer, Sale
from .forms import LoginForm

from .db import get_session
from .sales import _sales_keys
from .auth import login_required
from . import print_agent
from .allegro_token_refresher import token_refresher
from .env_info import ENV_INFO
from .config import settings
from .settings_store import SettingsPersistenceError, settings_store
from .settings_io import HIDDEN_KEYS

# Settings with boolean values represented as "1" or "0"
BOOLEAN_KEYS = {
    "ENABLE_MONTHLY_REPORTS",
    "ENABLE_WEEKLY_REPORTS",
    "FLASK_DEBUG",
}


bp = Blueprint("main", __name__)

# Backward compatibility placeholder
app = None

_print_agent_started = False


# =============================================================================
# Template Filters (registered via app)
# =============================================================================

@bp.app_template_filter("format_dt")
def format_dt(value, fmt="%d/%m/%Y %H:%M"):
    """Return datetime formatted with day/month/year."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return value[:16]
    return value.strftime(fmt)


@bp.app_template_filter("format_dt_short")
def format_dt_short(value):
    """Return datetime formatted as short day/month."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return value[:10]
    return value.strftime("%d/%m %H:%M")


@bp.app_template_filter("timestamp_to_date")
def timestamp_to_date(value, fmt="%d/%m/%Y"):
    """Convert Unix timestamp to formatted date string."""
    if value is None:
        return ""
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).strftime(fmt)
        return str(value)
    except (ValueError, OSError, TypeError):
        return str(value)


# =============================================================================
# Helper Functions
# =============================================================================

def _make_logger():
    if has_app_context():
        return lambda message, error: current_app.logger.exception(
            message, exc_info=error
        )
    return None


def _make_error_notifier():
    if has_request_context():
        def notifier(message):
            if "Settings template missing" in message:
                flash("Plik .env.example nie istnieje, brak ustawień do wyświetlenia.")
            else:
                flash(message)
        return notifier
    return None


def _api_token_ok(value: Optional[str]) -> bool:
    expected = settings.BASELINKER_WEBHOOK_TOKEN or settings.API_TOKEN
    if not expected:
        return False
    return hmac.compare_digest(str(value or ""), str(expected))


# =============================================================================
# Context Processors
# =============================================================================

@bp.app_context_processor
def inject_current_year():
    from .constants import PRODUCT_CATEGORIES, PRODUCT_BRANDS, PRODUCT_SERIES
    with get_session() as db:
        unread_count = db.query(Thread).filter_by(read=False).count()
    return {
        "current_year": datetime.now().year, 
        "unread_count": unread_count,
        "now": datetime.now,  # Function to get current time in templates
        "PRODUCT_CATEGORIES": PRODUCT_CATEGORIES,
        "PRODUCT_BRANDS": PRODUCT_BRANDS,
        "PRODUCT_SERIES": PRODUCT_SERIES,
    }


# =============================================================================
# Print Agent Management
# =============================================================================

def start_print_agent(app_obj=None):
    """Initialize and start the background label printing agent."""
    global _print_agent_started
    if _print_agent_started:
        return
    _print_agent_started = True
    app_ctx = app_obj or current_app
    agent = print_agent.agent
    started = False
    failed = False
    try:
        agent.validate_env()
        agent.ensure_db_init()
        started = agent.start_agent_thread()
    except print_agent.ConfigError as e:
        app_ctx.logger.error(f"Failed to start print agent: {e}")
        failed = True
    except Exception as e:
        app_ctx.logger.error(f"Failed to start print agent: {e}")
        failed = True
    finally:
        try:
            token_refresher.start()
        except Exception as exc:
            app_ctx.logger.error("Failed to start Allegro token refresher: %s", exc)
    if failed:
        _print_agent_started = False
        return
    if not started:
        app_ctx.logger.info("Print agent already running")
        _print_agent_started = False


def ensure_db_initialized(app_obj=None):
    """Ensure database path is valid and initialize tables."""
    try:
        db_path = settings.DB_PATH
        if os.path.isdir(db_path):
            logger = (app_obj or current_app).logger
            logger.error(f"Database path {db_path} is a directory. Please fix the mount.")
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.")
            raise SystemExit(1)
        if os.path.exists(db_path) and not os.path.isfile(db_path):
            logger = (app_obj or current_app).logger
            logger.error(f"Database path {db_path} is not a file.")
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.")
            raise SystemExit(1)
    except Exception as e:
        logger = (app_obj or current_app).logger
        logger.exception("Database initialization failed: %s", e)
        if has_request_context():
            flash(f"Błąd inicjalizacji bazy danych: {e}")


# =============================================================================
# API Routes
# =============================================================================

@bp.route("/api/eans", methods=["GET"])
def api_eans():
    """Public API endpoint for EAN codes."""
    provided = request.headers.get("X-Auth-Token") or request.args.get("token")
    if not _api_token_ok(provided):
        return make_response(jsonify({"error": "unauthorized"}), 401)

    with get_session() as db:
        rows = (
            db.query(
                ProductSize.barcode,
                Product.name,
                Product.color,
                ProductSize.size,
                ProductSize.quantity,
            )
            .join(Product, ProductSize.product_id == Product.id)
            .filter(ProductSize.barcode.isnot(None))
            .filter(ProductSize.barcode != "")
            .all()
        )

    items = [
        {
            "ean": barcode,
            "barcode": barcode,
            "name": name,
            "color": color,
            "size": size,
            "quantity": quantity,
        }
        for barcode, name, color, size, quantity in rows
    ]

    payload = {
        "count": len(items),
        "eans": [item["ean"] for item in items],
        "items": items,
    }

    resp = make_response(jsonify(payload), 200)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-store"
    return resp


# =============================================================================
# Core Routes
# =============================================================================

@bp.route("/")
@login_required
def home():
    from datetime import datetime, timedelta
    from sqlalchemy import func, desc
    from decimal import Decimal
    
    username = session["username"]
    
    with get_session() as db:
        # =====================================================================
        # Time periods
        # =====================================================================
        now = datetime.now()
        today_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        week_ago = int((now - timedelta(days=7)).timestamp())
        month_ago = int((now - timedelta(days=30)).timestamp())
        
        # =====================================================================
        # Orders statistics
        # =====================================================================
        # Today's orders
        orders_today = db.query(Order).filter(Order.date_add >= today_start).count()
        
        # This week orders
        orders_week = db.query(Order).filter(Order.date_add >= week_ago).count()
        
        # This month orders
        orders_month = db.query(Order).filter(Order.date_add >= month_ago).count()
        
        # Pending orders (not shipped yet - no tracking number)
        pending_orders = db.query(Order).filter(
            Order.delivery_package_nr.is_(None),
            Order.date_add >= month_ago
        ).count()
        
        # =====================================================================
        # Revenue statistics (from OrderProduct prices)
        # =====================================================================
        def calc_revenue(from_timestamp):
            result = db.query(func.sum(OrderProduct.price_brutto * OrderProduct.quantity))\
                .join(Order)\
                .filter(Order.date_add >= from_timestamp)\
                .scalar()
            return float(result or 0)
        
        revenue_today = calc_revenue(today_start)
        revenue_week = calc_revenue(week_ago)
        revenue_month = calc_revenue(month_ago)
        
        # =====================================================================
        # Inventory statistics
        # =====================================================================
        # Total products count
        total_products = db.query(Product).count()
        
        # Total stock (sum of all quantities)
        total_stock = db.query(func.sum(ProductSize.quantity)).scalar() or 0
        
        # Low stock products (quantity <= 2 but > 0) - convert to dicts
        low_stock_query = db.query(ProductSize, Product)\
            .join(Product)\
            .filter(ProductSize.quantity > 0, ProductSize.quantity <= 2)\
            .order_by(ProductSize.quantity.asc())\
            .limit(10)\
            .all()
        
        low_stock_items = []
        for size, product in low_stock_query:
            low_stock_items.append({
                'size': size.size,
                'quantity': size.quantity,
                'product_id': product.id,
                'product_name': product.name,
                'product_color': product.color,
            })
        
        # Out of stock count
        out_of_stock = db.query(ProductSize).filter(ProductSize.quantity == 0).count()
        
        # =====================================================================
        # Latest orders (last 10) - convert to dicts for template use
        # =====================================================================
        from sqlalchemy.orm import joinedload
        latest_orders_query = db.query(Order)\
            .options(joinedload(Order.products))\
            .order_by(desc(Order.date_add))\
            .limit(10)\
            .all()
        
        latest_orders = []
        for order in latest_orders_query:
            # Eagerly load products count
            products_count = len(order.products) if order.products else 0
            product_names = [p.name for p in order.products[:2]] if order.products else []
            latest_orders.append({
                'order_id': order.order_id,
                'customer_name': order.customer_name,
                'date_add': order.date_add,
                'delivery_package_nr': order.delivery_package_nr,
                'products_count': products_count,
                'product_names': product_names,
            })
        
        # =====================================================================
        # Latest deliveries/purchases (last 5 deliveries) - grouped by date/invoice
        # =====================================================================
        from sqlalchemy import func
        
        # Get distinct delivery dates/invoices (most recent first)
        delivery_groups = db.query(
            PurchaseBatch.purchase_date,
            PurchaseBatch.invoice_number,
            PurchaseBatch.supplier,
            func.count(PurchaseBatch.id).label('batch_count'),
            func.sum(PurchaseBatch.quantity).label('total_quantity'),
            func.sum(PurchaseBatch.quantity * PurchaseBatch.price).label('total_value')
        )\
        .group_by(PurchaseBatch.purchase_date, PurchaseBatch.invoice_number, PurchaseBatch.supplier)\
        .order_by(desc(PurchaseBatch.purchase_date))\
        .limit(5)\
        .all()
        
        latest_deliveries = []
        for date, invoice, supplier, batch_count, total_qty, total_value in delivery_groups:
            # Pomijamy dostawy z pustymi wartosciami (None z SQL NULL)
            if not total_qty or total_qty == 0 or not total_value or total_value == 0:
                continue
            
            # Pomijamy dostawy z nieprawidlowa data (00:00:00 lub pusta)
            if not date or date == '0000-00-00':
                continue
            
            # Get product details for this delivery
            products_in_delivery = db.query(PurchaseBatch, Product)\
                .join(Product)\
                .filter(
                    PurchaseBatch.purchase_date == date,
                    PurchaseBatch.invoice_number == invoice,
                    PurchaseBatch.supplier == supplier
                )\
                .all()
            
            product_details = []
            for batch, product in products_in_delivery:
                product_details.append({
                    'name': product.name,
                    'color': product.color,
                    'size': batch.size,
                    'quantity': batch.quantity,
                    'price': batch.price,
                    'value': batch.quantity * batch.price
                })
            
            latest_deliveries.append({
                'purchase_date': date,
                'invoice_number': invoice,
                'supplier': supplier,
                'batch_count': batch_count,
                'total_quantity': total_qty,
                'total_value': total_value,
                'products': product_details,
            })
        
        # =====================================================================
        # BESTSELLERY I TRENDY
        # =====================================================================
        
        # Helper do pobierania bestselerow z danego okresu
        def get_bestsellers(from_timestamp=None, limit=10):
            """Pobiera najlepiej sprzedajace sie produkty z linkami do produktow."""
            # Subquery do agregacji sprzedazy per EAN
            sales_subq = db.query(
                OrderProduct.name.label('order_name'),
                OrderProduct.ean,
                func.sum(OrderProduct.quantity).label('total_qty'),
                func.sum(OrderProduct.price_brutto * OrderProduct.quantity).label('total_revenue'),
                func.count(func.distinct(OrderProduct.order_id)).label('order_count')
            ).join(Order)
            
            if from_timestamp:
                sales_subq = sales_subq.filter(Order.date_add >= from_timestamp)
            
            sales_subq = sales_subq.group_by(OrderProduct.name, OrderProduct.ean).subquery()
            
            # Dolacz do ProductSize i Product aby miec product_id i dodatkowe dane
            results = db.query(
                sales_subq.c.order_name,
                sales_subq.c.ean,
                sales_subq.c.total_qty,
                sales_subq.c.total_revenue,
                sales_subq.c.order_count,
                Product.id.label('product_id'),
                Product.series,
                Product.color,
                ProductSize.size
            ).outerjoin(ProductSize, ProductSize.barcode == sales_subq.c.ean)\
            .outerjoin(Product, Product.id == ProductSize.product_id)\
            .order_by(desc(sales_subq.c.total_qty))\
            .limit(limit)\
            .all()
            
            items = []
            for order_name, ean, qty, revenue, orders, product_id, series, color, size in results:
                # Buduj krotka nazwe: seria/kolor/rozmiar
                short_parts = []
                if series:
                    short_parts.append(series)
                if color:
                    short_parts.append(color)
                if size:
                    short_parts.append(size)
                short_name = '/'.join(short_parts) if short_parts else (order_name or 'Brak nazwy')[:30]
                
                items.append({
                    'name': order_name or 'Brak nazwy',  # Pelna nazwa do tooltip
                    'short_name': short_name,  # Krotka nazwa do wyswietlenia
                    'ean': ean,
                    'quantity': int(qty or 0),
                    'revenue': float(revenue or 0),
                    'orders': int(orders or 0),
                    'product_id': product_id,  # Do linku
                })
            return items
        
        # Bestsellery wszechczasow (top 10)
        bestsellers_all_time = get_bestsellers(limit=10)
        
        # Bestsellery ostatnich 30 dni
        bestsellers_month = get_bestsellers(from_timestamp=month_ago, limit=10)
        
        # Bestsellery ostatnich 7 dni (trendy)
        bestsellers_week = get_bestsellers(from_timestamp=week_ago, limit=5)
        
        # =====================================================================
        # PRODUKTY WOLNOOBROTOWE (sprzedaz < 2 szt. w ciagu 30 dni mimo stanu > 5)
        # =====================================================================
        # Znajdz produkty ktore maja duzy stan ale sie nie sprzedaja
        
        # Subquery: sprzedaz w ostatnich 30 dniach per EAN
        recent_sales_subq = db.query(
            OrderProduct.ean,
            func.sum(OrderProduct.quantity).label('sold_qty')
        ).join(Order)\
        .filter(Order.date_add >= month_ago)\
        .group_by(OrderProduct.ean)\
        .subquery()
        
        # Produkty z duzym stanem ale mala sprzedaza
        slow_movers = db.query(
            Product.name,
            Product.color,
            ProductSize.size,
            ProductSize.quantity,
            func.coalesce(recent_sales_subq.c.sold_qty, 0).label('sold_30d')
        ).join(Product)\
        .outerjoin(recent_sales_subq, ProductSize.barcode == recent_sales_subq.c.ean)\
        .filter(
            ProductSize.quantity >= 5,  # Duzy stan magazynowy
            func.coalesce(recent_sales_subq.c.sold_qty, 0) < 2  # Mala sprzedaz
        )\
        .order_by(ProductSize.quantity.desc())\
        .limit(10)\
        .all()
        
        slow_moving_products = [
            {
                'name': name,
                'color': color,
                'size': size,
                'stock': qty,
                'sold_30d': int(sold)
            }
            for name, color, size, qty, sold in slow_movers
        ]
        
        # =====================================================================
        # POROWNANIE OKRESOW (trend wzrostu/spadku)
        # =====================================================================
        # Poprzedni tydzien vs aktualny tydzien
        two_weeks_ago = int((now - timedelta(days=14)).timestamp())
        
        prev_week_orders = db.query(Order).filter(
            Order.date_add >= two_weeks_ago,
            Order.date_add < week_ago
        ).count()
        
        prev_week_revenue = db.query(func.sum(OrderProduct.price_brutto * OrderProduct.quantity))\
            .join(Order)\
            .filter(Order.date_add >= two_weeks_ago, Order.date_add < week_ago)\
            .scalar() or 0
        
        # Oblicz zmiane procentowa
        orders_change = ((orders_week - prev_week_orders) / max(prev_week_orders, 1)) * 100
        revenue_change = ((revenue_week - float(prev_week_revenue)) / max(float(prev_week_revenue), 1)) * 100
        
        trends = {
            'orders_change': round(orders_change, 1),
            'revenue_change': round(revenue_change, 1),
            'prev_week_orders': prev_week_orders,
            'prev_week_revenue': float(prev_week_revenue),
        }
        
        # =====================================================================
        # Allegro offers - unlinked
        # =====================================================================
        unlinked_offers = db.query(AllegroOffer)\
            .filter(
                AllegroOffer.publication_status == 'ACTIVE',
                AllegroOffer.product_size_id.is_(None),
                AllegroOffer.product_id.is_(None)
            )\
            .count()
        
        total_offers = db.query(AllegroOffer)\
            .filter(AllegroOffer.publication_status == 'ACTIVE')\
            .count()
        
        # =====================================================================
        # Recent activity log
        # =====================================================================
        # Build activity from orders and deliveries
        activities = []
        
        # Add recent orders to activity (latest_orders is now list of dicts)
        for order in latest_orders[:5]:
            if order['date_add']:
                order_date = datetime.fromtimestamp(order['date_add'])
                products_str = ", ".join(order['product_names'])
                if order['products_count'] > 2:
                    products_str += f" +{order['products_count'] - 2}"
                activities.append({
                    'type': 'order',
                    'icon': 'bi-cart-check',
                    'color': 'success',
                    'title': f'Nowe zamówienie #{order["order_id"][-6:]}',
                    'description': f'{order["customer_name"] or "Klient"}: {products_str}',
                    'timestamp': order_date,
                    'link': url_for('orders.order_detail', order_id=order['order_id'])
                })
        
        # Add recent deliveries to activity (latest_deliveries is now grouped by delivery)
        for delivery in latest_deliveries[:3]:
            try:
                batch_date = datetime.strptime(delivery['purchase_date'], '%Y-%m-%d')
            except:
                batch_date = now
            
            # Show supplier or invoice if available
            title_suffix = delivery['supplier'] or delivery['invoice_number'] or f"{delivery['total_quantity']} szt."
            
            activities.append({
                'type': 'delivery',
                'icon': 'bi-box-seam',
                'color': 'info',
                'title': f'Dostawa: {title_suffix}',
                'description': f'{delivery["total_quantity"]} szt. za {delivery["total_value"]:.2f} zł ({delivery["batch_count"]} modeli)',
                'timestamp': batch_date,
                'link': url_for('products.items')  # Link to products list since it's a delivery
            })
        
        # Sort activities by timestamp
        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        activities = activities[:8]  # Keep top 8
        
        # =====================================================================
        # Build dashboard data
        # =====================================================================
        dashboard = {
            'orders': {
                'today': orders_today,
                'week': orders_week,
                'month': orders_month,
                'pending': pending_orders,
            },
            'revenue': {
                'today': revenue_today,
                'week': revenue_week,
                'month': revenue_month,
            },
            'inventory': {
                'total_products': total_products,
                'total_stock': total_stock,
                'out_of_stock': out_of_stock,
                'low_stock_items': low_stock_items,
            },
            'allegro': {
                'total_offers': total_offers,
                'unlinked_offers': unlinked_offers,
            },
            'latest_orders': latest_orders,
            'latest_deliveries': latest_deliveries,
            'activities': activities,
            # Nowe sekcje - bestsellery i trendy
            'bestsellers': {
                'all_time': bestsellers_all_time,
                'month': bestsellers_month,
                'week': bestsellers_week,
            },
            'slow_moving': slow_moving_products,
            'trends': trends,
        }
    
    return render_template("home.html", username=username, dashboard=dashboard)


@bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        valid = False
        with get_session() as db:
            user = db.query(User).filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                valid = True

        if valid:
            session["username"] = username
            return redirect(url_for("home"))
        else:
            flash("Niepoprawna nazwa użytkownika lub hasło")
        return redirect(url_for("login"))

    return render_template("login.html", form=form, show_menu=False)


@bp.route("/logout")
@login_required
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    all_values = settings_store.as_ordered_dict(
        include_hidden=True,
        logger=_make_logger(),
        on_error=_make_error_notifier(),
    )
    values = OrderedDict(
        (key, val) for key, val in all_values.items() if key not in HIDDEN_KEYS
    )
    sales_keys = _sales_keys(values)
    db_path_notice = bool(all_values.get("DB_PATH"))
    
    if request.method == "POST":
        updates = {}
        for key in list(values.keys()):
            if key in sales_keys:
                continue
            updates[key] = request.form.get(key, values.get(key, ""))
        for tkey in ("QUIET_HOURS_START", "QUIET_HOURS_END"):
            try:
                print_agent.parse_time_str(updates.get(tkey, values.get(tkey, "")))
            except ValueError:
                flash("Niepoprawny format godziny (hh:mm)")
                return redirect(url_for("settings_page"))
        try:
            settings_store.update(updates)
        except SettingsPersistenceError as exc:
            current_app.logger.error(
                "Failed to persist settings submitted via the admin panel", exc_info=exc
            )
            flash(
                "Nie można zapisać ustawień, ponieważ baza konfiguracji jest w trybie tylko do odczytu."
            )
            return redirect(url_for("settings_page"))
        print_agent.reload_config()
        flash("Zapisano ustawienia.")
        return redirect(url_for("settings_page"))
    
    settings_list = []
    for key, val in values.items():
        if key in sales_keys:
            continue
        label, desc = ENV_INFO.get(key, (key, None))
        settings_list.append(
            {"key": key, "label": label, "desc": desc, "value": val}
        )
    return render_template(
        "settings.html",
        settings=settings_list,
        db_path_notice=db_path_notice,
        boolean_keys=BOOLEAN_KEYS,
    )


@bp.route("/logs")
@login_required
def agent_logs():
    try:
        with open(print_agent.LOG_FILE, "r") as f:
            lines = f.readlines()[-200:]
        log_text = "<br>".join(line.rstrip() for line in lines[::-1])
    except Exception as e:
        log_text = f"Błąd czytania logów: {e}"
    return render_template("logs.html", logs=log_text)


@bp.route("/testprint", methods=["GET", "POST"])
@login_required
def test_print():
    message = None
    if request.method == "POST":
        success = print_agent.print_test_page()
        message = (
            "Testowy wydruk wysłany." if success else "Błąd testowego wydruku."
        )
    return render_template("testprint.html", message=message)


@bp.route("/test", methods=["GET", "POST"])
@login_required
def test_message():
    msg = None
    if request.method == "POST":
        if print_agent.last_order_data:
            print_agent.send_messenger_message(print_agent.last_order_data)
            msg = "Testowa wiadomość została wysłana."
        else:
            msg = "Brak danych ostatniego zamówienia."
    return render_template("test.html", message=msg)


# =============================================================================
# Error Handlers
# =============================================================================

@bp.app_errorhandler(404)
def handle_404(error):
    """Render custom page for 404 errors."""
    return render_template("404.html"), 404


@bp.app_errorhandler(500)
def handle_500(error):
    """Render custom page for internal server errors."""
    return render_template("500.html"), 500


# =============================================================================
# Utility Routes
# =============================================================================

@bp.route("/download/scraper")
@login_required
def download_scraper():
    """Download portable Allegro scraper package"""
    script_dir = Path(__file__).parent / "scripts"
    files = {
        "scraper_api.py": script_dir / "scraper_api.py",
        "SETUP.bat": script_dir / "SETUP.bat",
        "README_SCRAPER.txt": script_dir / "README_SCRAPER.txt",
    }
    
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for filename, filepath in files.items():
            if filepath.exists():
                zipf.write(filepath, f"AllegroScraper/{filename}")
    
    memory_file.seek(0)
    
    response = make_response(memory_file.getvalue())
    response.headers['Content-Type'] = 'application/zip'
    response.headers['Content-Disposition'] = 'attachment; filename=AllegroScraper_Portable.zip'
    
    return response
