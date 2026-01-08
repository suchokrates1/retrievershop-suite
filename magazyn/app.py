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

from .models import User, Thread, Product, ProductSize
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
    with get_session() as db:
        unread_count = db.query(Thread).filter_by(read=False).count()
    return {"current_year": datetime.now().year, "unread_count": unread_count}


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
    username = session["username"]
    return render_template("home.html", username=username)


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
