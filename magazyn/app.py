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
    jsonify,
)
from datetime import datetime
import os
from werkzeug.security import check_password_hash

from .models.messages import Thread
from .models.users import User
from .forms import LoginForm

from .db import get_session
from .auth import login_required
from .print_agent import agent as label_agent
from .config import settings
from .settings_store import settings_store
from .services.app_runtime import start_print_agent_runtime
from .services.print_agent_config import ConfigError
from .services.settings_page import build_settings_context, update_settings_from_form
from .services.fixed_costs import (
    add_fixed_cost as add_fixed_cost_record,
    delete_fixed_cost as delete_fixed_cost_record,
    edit_fixed_cost as edit_fixed_cost_record,
    toggle_fixed_cost as toggle_fixed_cost_record,
)


bp = Blueprint("main", __name__)


def _test_routes_enabled() -> bool:
    return bool(current_app.debug or os.environ.get("ENABLE_TEST_ROUTES") == "1")


def _redirect_disabled_test_route():
    flash("Endpoint testowy jest wyłączony w tym środowisku.", "warning")
    return redirect(url_for("settings_page"))


@bp.get("/cenyiaukcjeinfo")
def ceny_i_aukcje_info():
    """Strona informacyjna aplikacji Allegro REST API (wymagana przez User-Agent)."""
    return (
        "<html><head><title>Ceny i aukcje - informacje</title></head><body>"
        "<h1>Ceny i aukcje</h1>"
        "<p>Aplikacja do zarzadzania zamowieniami, przesylkami i ofertami "
        "na platformie Allegro.</p>"
        "<p>Operator: Retriever Shop</p>"
        "<p>Kontakt: kontakt@retrievershop.pl</p>"
        "</body></html>"
    ), 200, {"Content-Type": "text/html; charset=utf-8"}


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
    result = start_print_agent_runtime(app_ctx, label_agent, ConfigError)
    # Token refresher is started via gunicorn hook (single worker only).
    if result.failed:
        _print_agent_started = False
        return
    if not result.started:
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
    from .domain.dashboard import DashboardService
    from .settings_store import settings_store as ss
    started_at = datetime.now()
    
    access_token = ss.get("ALLEGRO_ACCESS_TOKEN")
    current_app.logger.info(
        "REQUEST START [dashboard-heavy] /api/dashboard/heavy access_token=%s",
        bool(access_token),
    )
    
    with get_session() as db:
        service = DashboardService(db, ss)
        heavy_data = service.get_heavy_dashboard(access_token)

    elapsed_ms = (datetime.now() - started_at).total_seconds() * 1000
    current_app.logger.info(
        "REQUEST END [dashboard-heavy] /api/dashboard/heavy elapsed_ms=%.1f keys=%s",
        elapsed_ms,
        sorted(list(heavy_data.keys())),
    )
    
    return jsonify(heavy_data)


@bp.route("/stats")
@login_required
def stats_dashboard():
    """Widok dashboardu statystyk (Sprint 5)."""
    username = session["username"]
    return render_template("stats_dashboard.html", username=username)


@bp.route("/stats/billing-types")
@login_required
def stats_billing_types():
    """Dedykowana podstrona mapowania typow rozliczen Allegro."""
    username = session["username"]
    return render_template("billing_types_mapping.html", username=username)


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
    if request.method == "POST":
        result = update_settings_from_form(request.form, current_app.logger)
        if result.should_reload_agent:
            label_agent.reload_config()
        flash(result.message, result.category)
        return redirect(url_for("settings_page"))
    context = build_settings_context(logger=_make_logger(), on_error=_make_error_notifier())
    return render_template(
        "settings.html",
        **context,
    )


@bp.route("/fixed-costs/add", methods=["POST"])
@login_required
def add_fixed_cost():
    """Dodaj nowy koszt staly."""
    result = add_fixed_cost_record(
        request.form.get("name", ""),
        request.form.get("amount", "0"),
        request.form.get("description", ""),
    )
    flash(result.message, result.category)
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/toggle", methods=["POST"])
@login_required
def toggle_fixed_cost(cost_id):
    """Wlacz/wylacz koszt staly."""
    result = toggle_fixed_cost_record(cost_id)
    flash(result.message, result.category)
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/delete", methods=["POST"])
@login_required
def delete_fixed_cost(cost_id):
    """Usun koszt staly."""
    result = delete_fixed_cost_record(cost_id)
    flash(result.message, result.category)
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/edit", methods=["POST"])
@login_required
def edit_fixed_cost(cost_id):
    """Edytuj koszt staly."""
    result = edit_fixed_cost_record(
        cost_id,
        request.form.get("name", ""),
        request.form.get("amount", "0"),
        request.form.get("description", ""),
    )
    flash(result.message, result.category)
    return redirect(url_for("settings_page"))


@bp.route("/logs")
@login_required
def agent_logs():
    try:
        import html as html_mod
        with open(label_agent.config.log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]
        log_text = "<br>".join(html_mod.escape(line.rstrip()) for line in lines[::-1])
    except Exception as e:
        log_text = f"Blad czytania logow: {e}"
    return render_template("logs.html", logs=log_text)


@bp.route("/testprint", methods=["GET", "POST"])
@login_required
def test_print():
    if not _test_routes_enabled():
        return _redirect_disabled_test_route()
    message = None
    if request.method == "POST":
        success = label_agent.print_test_page()
        message = (
            "Testowy wydruk wysłany." if success else "Błąd testowego wydruku."
        )
    return render_template("testprint.html", message=message)


@bp.route("/test", methods=["GET", "POST"])
@login_required
def test_message():
    if not _test_routes_enabled():
        return _redirect_disabled_test_route()
    msg = None
    if request.method == "POST":
        if label_agent.last_order_data:
            label_agent.send_messenger_message(label_agent.last_order_data)
            msg = "Testowa wiadomosc zostala wyslana."
        else:
            msg = "Brak danych ostatniego zamowienia."
    return render_template("test.html", message=msg)


@bp.route("/test_monthly_report", methods=["GET", "POST"])
@login_required
def test_monthly_report():
    """Wyslij testowy raport miesiczny przez Messenger."""
    if not _test_routes_enabled():
        return _redirect_disabled_test_route()
    from .notifications import send_report
    from .services.test_reports import send_current_month_test_report

    msg = None
    summary = None
    if request.method == "POST":
        payload = send_current_month_test_report(
            get_session,
            settings_store,
            send_report,
        )
        msg = payload.message
        summary = payload.summary
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
