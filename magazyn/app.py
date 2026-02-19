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
from .domain.financial import FinancialCalculator

# Settings with boolean values represented as "1" or "0"
BOOLEAN_KEYS = {
    "ENABLE_MONTHLY_REPORTS",
    "ENABLE_WEEKLY_REPORTS",
    "FLASK_DEBUG",
}

# Grupowanie ustawien w sekcje (klucz -> (nazwa_grupy, ikona))
SETTINGS_GROUPS = {
    "API_TOKEN": ("API i Integracje", "bi-plug"),
    "BASELINKER_WEBHOOK_TOKEN": ("API i Integracje", "bi-plug"),
    "ALLEGRO_SCRAPER_API_URL": ("Allegro", "bi-shop"),
    "ALLEGRO_PROXY_URL": ("Allegro", "bi-shop"),
    "COMMISSION_ALLEGRO": ("Allegro", "bi-shop"),
    "PRICE_MAX_DISCOUNT_PERCENT": ("Allegro", "bi-shop"),
    "PRINTER_NAME": ("Drukarka", "bi-printer"),
    "CUPS_SERVER": ("Drukarka", "bi-printer"),
    "CUPS_PORT": ("Drukarka", "bi-printer"),
    "POLL_INTERVAL": ("Agent drukujacy", "bi-robot"),
    "QUIET_HOURS_START": ("Agent drukujacy", "bi-robot"),
    "QUIET_HOURS_END": ("Agent drukujacy", "bi-robot"),
    "STATUS_ID": ("Agent drukujacy", "bi-robot"),
    "PRINTED_EXPIRY_DAYS": ("Agent drukujacy", "bi-robot"),
    "PAGE_ACCESS_TOKEN": ("Powiadomienia", "bi-bell"),
    "RECIPIENT_ID": ("Powiadomienia", "bi-bell"),
    "LOW_STOCK_THRESHOLD": ("Powiadomienia", "bi-bell"),
    "ALERT_EMAIL": ("Powiadomienia", "bi-bell"),
    "SMTP_SERVER": ("Powiadomienia", "bi-bell"),
    "SMTP_PORT": ("Powiadomienia", "bi-bell"),
    "SMTP_USERNAME": ("Powiadomienia", "bi-bell"),
    "SMTP_PASSWORD": ("Powiadomienia", "bi-bell"),
    "ENABLE_WEEKLY_REPORTS": ("Raporty", "bi-bar-chart"),
    "ENABLE_MONTHLY_REPORTS": ("Raporty", "bi-bar-chart"),
    "PACKAGING_COST": ("Sprzedaz", "bi-cash"),
    "LOG_LEVEL": ("System", "bi-gear"),
    "LOG_FILE": ("System", "bi-gear"),
    "SECRET_KEY": ("System", "bi-gear"),
    "FLASK_DEBUG": ("System", "bi-gear"),
    "FLASK_ENV": ("System", "bi-gear"),
    "TIMEZONE": ("System", "bi-gear"),
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
                flash("Plik .env.example nie istnieje, brak ustawień do wyświetlenia.", "warning")
            else:
                flash(message, "warning")
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
                flash("Błąd konfiguracji bazy danych.", "error")
            raise SystemExit(1)
        if os.path.exists(db_path) and not os.path.isfile(db_path):
            logger = (app_obj or current_app).logger
            logger.error(f"Database path {db_path} is not a file.")
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.", "error")
            raise SystemExit(1)
    except Exception as e:
        logger = (app_obj or current_app).logger
        logger.exception("Database initialization failed: %s", e)
        if has_request_context():
            flash(f"Błąd inicjalizacji bazy danych: {e}", "error")


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
    """Strona glowna - dashboard z podsumowaniem (szybki load)."""
    from .domain.dashboard import DashboardService
    from .settings_store import settings_store as ss
    
    username = session["username"]
    
    with get_session() as db:
        service = DashboardService(db, ss)
        dashboard = service.get_fast_dashboard()
        
        # Dodaj aktywnosc (wymaga url_for)
        dashboard['activities'] = service.get_recent_activity(
            dashboard['latest_orders'],
            dashboard['latest_deliveries'],
            url_for,
            limit=8
        )
    
    return render_template("home.html", username=username, dashboard=dashboard)


@bp.route("/api/dashboard/heavy")
@login_required
def dashboard_heavy():
    """Endpoint API dla ciezkich danych dashboardu (lazy loading)."""
    from flask import jsonify
    from .domain.dashboard import DashboardService
    from .settings_store import settings_store as ss
    
    access_token = ss.get("ALLEGRO_ACCESS_TOKEN")
    
    with get_session() as db:
        service = DashboardService(db, ss)
        heavy_data = service.get_heavy_dashboard(access_token)
    
    return jsonify(heavy_data)


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
            flash("Niepoprawna nazwa użytkownika lub hasło", "error")
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
                flash("Niepoprawny format godziny (hh:mm)", "error")
                return redirect(url_for("settings_page"))
        try:
            settings_store.update(updates)
        except SettingsPersistenceError as exc:
            current_app.logger.error(
                "Failed to persist settings submitted via the admin panel", exc_info=exc
            )
            flash(
                "Nie można zapisać ustawień, ponieważ baza konfiguracji jest w trybie tylko do odczytu.",
                "error",
            )
            return redirect(url_for("settings_page"))
        print_agent.reload_config()
        flash("Zapisano ustawienia.", "success")
        return redirect(url_for("settings_page"))
    
    settings_list = []
    for key, val in values.items():
        if key in sales_keys:
            continue
        label, desc = ENV_INFO.get(key, (key, None))
        group_name, group_icon = SETTINGS_GROUPS.get(key, ("Inne", "bi-three-dots"))
        settings_list.append(
            {"key": key, "label": label, "desc": desc, "value": val, "group": group_name, "group_icon": group_icon}
        )
    
    # Grupuj ustawienia w sekcje (zachowuj kolejnosc)
    from collections import OrderedDict as OD
    grouped_settings = OD()
    for item in settings_list:
        gname = item["group"]
        if gname not in grouped_settings:
            grouped_settings[gname] = {"icon": item["group_icon"], "items": []}
        grouped_settings[gname]["items"].append(item)
    
    # Pobierz koszty stale
    from .models import FixedCost
    with get_session() as db_session:
        fixed_costs = db_session.query(FixedCost).order_by(FixedCost.name).all()
        # Konwertuj na liste slownikow zeby uniknac problemow z sesja
        fixed_costs_list = [{
            'id': fc.id,
            'name': fc.name,
            'amount': float(fc.amount),
            'description': fc.description,
            'is_active': fc.is_active,
        } for fc in fixed_costs]
        total_fixed_costs = sum(fc['amount'] for fc in fixed_costs_list if fc['is_active'])
    
    return render_template(
        "settings.html",
        settings=settings_list,
        grouped_settings=grouped_settings,
        db_path_notice=db_path_notice,
        boolean_keys=BOOLEAN_KEYS,
        fixed_costs=fixed_costs_list,
        total_fixed_costs=total_fixed_costs,
    )


@bp.route("/fixed-costs/add", methods=["POST"])
@login_required
def add_fixed_cost():
    """Dodaj nowy koszt staly."""
    from .models import FixedCost
    from decimal import Decimal, InvalidOperation
    
    name = request.form.get("name", "").strip()
    amount_str = request.form.get("amount", "0").strip().replace(",", ".")
    description = request.form.get("description", "").strip()
    
    if not name:
        flash("Nazwa kosztu jest wymagana.", "error")
        return redirect(url_for("settings_page"))
    
    try:
        amount = Decimal(amount_str)
    except (InvalidOperation, ValueError):
        flash("Nieprawidlowa kwota.", "error")
        return redirect(url_for("settings_page"))
    
    new_cost = FixedCost(
        name=name,
        amount=amount,
        description=description if description else None,
        is_active=True,
    )
    with get_session() as db_session:
        db_session.add(new_cost)
        db_session.commit()
    
    flash(f"Dodano koszt staly: {name} ({amount} PLN)", "success")
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/toggle", methods=["POST"])
@login_required
def toggle_fixed_cost(cost_id):
    """Wlacz/wylacz koszt staly."""
    from .models import FixedCost
    
    with get_session() as db_session:
        cost = db_session.query(FixedCost).filter_by(id=cost_id).first()
        if cost:
            cost.is_active = not cost.is_active
            db_session.commit()
            status = "aktywny" if cost.is_active else "nieaktywny"
            flash(f"Koszt '{cost.name}' jest teraz {status}.", "info")
        else:
            flash("Nie znaleziono kosztu.", "error")
    
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/delete", methods=["POST"])
@login_required
def delete_fixed_cost(cost_id):
    """Usun koszt staly."""
    from .models import FixedCost
    
    with get_session() as db_session:
        cost = db_session.query(FixedCost).filter_by(id=cost_id).first()
        if cost:
            name = cost.name
            db_session.delete(cost)
            db_session.commit()
            flash(f"Usunieto koszt staly: {name}", "success")
        else:
            flash("Nie znaleziono kosztu.", "error")
    
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/edit", methods=["POST"])
@login_required
def edit_fixed_cost(cost_id):
    """Edytuj koszt staly."""
    from .models import FixedCost
    from decimal import Decimal, InvalidOperation
    
    with get_session() as db_session:
        cost = db_session.query(FixedCost).filter_by(id=cost_id).first()
        if not cost:
            flash("Nie znaleziono kosztu.", "error")
            return redirect(url_for("settings_page"))
        
        name = request.form.get("name", "").strip()
        amount_str = request.form.get("amount", "0").strip().replace(",", ".")
        description = request.form.get("description", "").strip()
        
        if not name:
            flash("Nazwa kosztu jest wymagana.", "error")
            return redirect(url_for("settings_page"))
        
        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            flash("Nieprawidlowa kwota.", "error")
            return redirect(url_for("settings_page"))
        
        cost.name = name
        cost.amount = amount
        cost.description = description if description else None
        db_session.commit()
        
        flash(f"Zaktualizowano koszt staly: {name}", "success")
    return redirect(url_for("settings_page"))


@bp.route("/logs")
@login_required
def agent_logs():
    try:
        with open(print_agent.LOG_FILE, "r") as f:
            lines = f.readlines()[-200:]
        log_text = "<br>".join(line.rstrip() for line in lines[::-1])
    except Exception as e:
        log_text = f"Blad czytania logow: {e}"
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
            msg = "Testowa wiadomosc zostala wyslana."
        else:
            msg = "Brak danych ostatniego zamowienia."
    return render_template("test.html", message=msg)


@bp.route("/test_monthly_report", methods=["GET", "POST"])
@login_required
def test_monthly_report():
    """Wyslij testowy raport miesiczny przez Messenger."""
    from datetime import datetime
    from .notifications import send_report
    
    msg = None
    summary = None
    
    if request.method == "POST":
        # Oblicz podsumowanie dla biezacego miesiaca (od 1.)
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_ts = int(month_start.timestamp())
        now_ts = int(now.timestamp())
        
        MONTH_NAMES = ['Styczen', 'Luty', 'Marzec', 'Kwiecien', 'Maj', 'Czerwiec',
                       'Lipiec', 'Sierpien', 'Wrzesien', 'Pazdziernik', 'Listopad', 'Grudzien']
        month_name = MONTH_NAMES[now.month - 1]
        
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        
        with get_session() as db:
            # Uzyj centralnego kalkulatora finansowego
            calculator = FinancialCalculator(db, settings_store)
            period_summary = calculator.get_period_summary(
                month_start_ts, 
                now_ts,
                include_fixed_costs=False,  # Raport testowy bez kosztow stalych
                access_token=access_token
            )
        
        summary = {
            "month_name": month_name,
            "products_sold": period_summary.products_sold,
            "total_revenue": float(period_summary.total_revenue),
            "real_profit": float(period_summary.gross_profit),
        }
        
        # Wyslij raport
        message = (
            f"W miesiącu {month_name} sprzedałaś {period_summary.products_sold} produktów "
            f"za {period_summary.total_revenue:.2f} zł co dało {period_summary.gross_profit:.2f} zł zysku"
        )
        send_report("Testowy raport miesieczny", [message])
        msg = f"Raport wyslany! Tresc: {message}"
    
    return render_template("test_report.html", message=msg, summary=summary)


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
