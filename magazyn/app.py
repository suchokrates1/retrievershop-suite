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
)
from datetime import datetime
import secrets
import os
import sys
from urllib.parse import urlencode
from werkzeug.security import check_password_hash
from collections import OrderedDict

from .models import User
from .forms import LoginForm

from .db import (
    get_session,
    init_db,
    reset_db,
    register_default_user,
    record_purchase,
    consume_stock,
)
from .sales import _sales_keys
from .auth import login_required
from . import print_agent
from .allegro_token_refresher import token_refresher
from .env_info import ENV_INFO
from magazyn import DB_PATH
from .settings_store import SettingsPersistenceError, settings_store
from .settings_io import (
    ENV_PATH,
    EXAMPLE_PATH,
    HIDDEN_KEYS,
    write_env as write_env_file,
)

# Settings with boolean values represented as "1" or "0"
BOOLEAN_KEYS = {
    "ENABLE_MONTHLY_REPORTS",
    "ENABLE_WEEKLY_REPORTS",
    "FLASK_DEBUG",
}


bp = Blueprint("main", __name__)

ALLEGRO_AUTHORIZATION_URL = "https://allegro.pl/auth/oauth/authorize"

# Backward compatibility placeholder populated in tests and scripts
app = None


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

_print_agent_started = False


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


def load_settings(include_hidden: bool = False):
    """Return application settings ordered for display."""

    return settings_store.as_ordered_dict(
        include_hidden=include_hidden,
        logger=_make_logger(),
        on_error=_make_error_notifier(),
    )


def write_env(values):
    """Persist values to ``.env`` as a fallback when the database is unavailable."""

    write_env_file(
        values,
        example_path=EXAMPLE_PATH,
        env_path=ENV_PATH,
        logger=_make_logger(),
        on_error=_make_error_notifier(),
    )


@bp.app_context_processor
def inject_current_year():
    return {"current_year": datetime.now().year}


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
        except Exception as exc:  # pragma: no cover - defensive
            app_ctx.logger.error(
                "Failed to start Allegro token refresher: %s", exc
            )
    if failed:
        _print_agent_started = False
        return
    if not started:
        app_ctx.logger.info("Print agent already running")
        _print_agent_started = False


def ensure_db_initialized(app_obj=None):
    try:
        if os.path.isdir(DB_PATH):
            logger = (app_obj or current_app).logger
            logger.error(
                (
                    f"Database path {DB_PATH} is a directory. "
                    "Please fix the mount."
                )
            )
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.")
            raise SystemExit(1)
        if os.path.exists(DB_PATH) and not os.path.isfile(DB_PATH):
            logger = (app_obj or current_app).logger
            logger.error(f"Database path {DB_PATH} is not a file.")
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.")
            raise SystemExit(1)

        # Always run table creation so new tables appear automatically.
        init_db()
        register_default_user()
    except Exception as e:
        logger = (app_obj or current_app).logger
        logger.exception("Database initialization failed: %s", e)
        if has_request_context():
            flash(f"Błąd inicjalizacji bazy danych: {e}")


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


@bp.post("/allegro/authorize")
@login_required
def allegro_authorize():
    client_id = settings_store.get("ALLEGRO_CLIENT_ID")
    redirect_uri = settings_store.get("ALLEGRO_REDIRECT_URI")
    if not client_id or not redirect_uri:
        flash("Uzupełnij konfigurację Allegro, aby rozpocząć autoryzację.")
        return redirect(url_for("settings_page"))

    state = secrets.token_urlsafe(16)
    session["allegro_oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    authorization_url = f"{ALLEGRO_AUTHORIZATION_URL}?{urlencode(params)}"
    return redirect(authorization_url)


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


@bp.app_errorhandler(404)
def handle_404(error):
    """Render custom page for 404 errors."""
    return render_template("404.html"), 404


@bp.app_errorhandler(500)
def handle_500(error):
    """Render custom page for internal server errors."""
    return render_template("500.html"), 500


if __name__ == "__main__":
    from .factory import create_app

    cli_app = create_app()
    if len(sys.argv) > 1 and sys.argv[1] == "init_db":
        with cli_app.app_context():
            ensure_db_initialized(cli_app)
    else:
        cli_app.run(
            host="0.0.0.0",
            port=80,
            debug=settings_store.settings.FLASK_DEBUG,
        )
