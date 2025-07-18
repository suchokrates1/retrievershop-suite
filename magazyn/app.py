from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    has_request_context,
)
from flask_wtf import CSRFProtect
from datetime import datetime
import os
import sys
import atexit
from werkzeug.security import check_password_hash
from dotenv import dotenv_values
from collections import OrderedDict
from pathlib import Path

from .models import User
from .forms import LoginForm

from .db import (
    get_session,
    init_db,
    reset_db,
    ensure_schema,
    register_default_user,
    record_purchase,
    consume_stock,
)
from .products import bp as products_bp
from .history import bp as history_bp
from .sales import bp as sales_bp, _sales_keys
from .shipping import bp as shipping_bp
from .auth import login_required
from .config import settings
from . import print_agent
from .env_info import ENV_INFO
from magazyn import DB_PATH
from .constants import ALL_SIZES

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
EXAMPLE_PATH = ROOT_DIR / ".env.example"

# Settings with boolean values represented as "1" or "0"
BOOLEAN_KEYS = {
    "ENABLE_MONTHLY_REPORTS",
    "ENABLE_WEEKLY_REPORTS",
    "FLASK_DEBUG",
}


app = Flask(__name__)
app.secret_key = settings.SECRET_KEY
CSRFProtect(app)
app.jinja_env.globals["ALL_SIZES"] = ALL_SIZES


@app.template_filter("format_dt")
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

app.register_blueprint(products_bp)
app.register_blueprint(history_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(shipping_bp)


@app.context_processor
def inject_current_year():
    return {"current_year": datetime.now().year}


def start_print_agent():
    """Initialize and start the background label printing agent."""
    global _print_agent_started
    if _print_agent_started:
        return
    _print_agent_started = True
    try:
        print_agent.validate_env()
        print_agent.ensure_db_init()
        started = print_agent.start_agent_thread()
        if not started:
            app.logger.info("Print agent already running")
            _print_agent_started = False
            return
    except print_agent.ConfigError as e:
        app.logger.error(f"Failed to start print agent: {e}")
    except Exception as e:
        app.logger.error(f"Failed to start print agent: {e}")


def load_settings():
    """Return OrderedDict combining keys from the example and current .env."""
    if not EXAMPLE_PATH.exists():
        app.logger.error(f"Settings template missing: {EXAMPLE_PATH}")
        flash("Plik .env.example nie istnieje, brak ustawień do wyświetlenia.")
        return OrderedDict()
    try:
        example = dotenv_values(EXAMPLE_PATH)
        current = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    except Exception as e:
        app.logger.exception("Failed to load .env files: %s", e)
        if has_request_context():
            flash(f"Błąd czytania plików .env: {e}")
        return OrderedDict()
    values = OrderedDict()

    # first preserve ordering from .env.example
    for key in example.keys():
        values[key] = current.get(key, example[key])

    # append any additional keys from the existing .env
    for key, val in current.items():
        if key not in values:
            values[key] = val

    # remove deprecated/unused keys
    for hidden in ("ENABLE_HTTP_SERVER", "HTTP_PORT", "DB_PATH"):
        values.pop(hidden, None)

    return values


def write_env(values):
    """Rewrite .env preserving example order and keeping unknown keys."""
    try:
        example = dotenv_values(EXAMPLE_PATH)
        example_keys = list(example.keys())
        current = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
        ordered = example_keys + [
            k for k in values.keys() if k not in example_keys
        ]
    except Exception as e:
        app.logger.exception("Failed to read env template: %s", e)
        if has_request_context():
            flash(f"Błąd odczytu {EXAMPLE_PATH}: {e}")
        return
    try:
        with ENV_PATH.open("w") as f:
            for key in ordered:
                val = values.get(key, current.get(key, example.get(key, "")))
                f.write(f"{key}={val}\n")
    except Exception as e:
        app.logger.exception("Failed to write .env file: %s", e)
        if has_request_context():
            flash(f"Błąd zapisu pliku .env: {e}")


def ensure_db_initialized():
    try:
        if os.path.isdir(DB_PATH):
            app.logger.error(
                (
                    f"Database path {DB_PATH} is a directory. "
                    "Please fix the mount."
                )
            )
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.")
            raise SystemExit(1)
        if os.path.exists(DB_PATH) and not os.path.isfile(DB_PATH):
            app.logger.error(f"Database path {DB_PATH} is not a file.")
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.")
            raise SystemExit(1)

        # Always run table creation so new tables appear automatically.
        init_db()
        ensure_schema()
        register_default_user()
    except Exception as e:
        app.logger.exception("Database initialization failed: %s", e)
        if has_request_context():
            flash(f"Błąd inicjalizacji bazy danych: {e}")


start_print_agent()
atexit.register(print_agent.stop_agent_thread)

ensure_db_initialized()


@app.route("/")
@login_required
def home():
    username = session["username"]
    return render_template("home.html", username=username)


@app.route("/login", methods=["GET", "POST"])
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


@app.route("/logout")
@login_required
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    values = load_settings()
    sales_keys = _sales_keys(values)
    db_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    db_path_notice = "DB_PATH" in db_vals
    if request.method == "POST":
        for key in list(values.keys()):
            if key in sales_keys:
                continue
            values[key] = request.form.get(key, "")
        for tkey in ("QUIET_HOURS_START", "QUIET_HOURS_END"):
            try:
                print_agent.parse_time_str(values.get(tkey, ""))
            except ValueError:
                flash("Niepoprawny format godziny (hh:mm)")
                return redirect(url_for("settings_page"))
        write_env(values)
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


@app.route("/logs")
@login_required
def agent_logs():
    try:
        with open(print_agent.LOG_FILE, "r") as f:
            lines = f.readlines()[-200:]
        log_text = "<br>".join(line.rstrip() for line in lines[::-1])
    except Exception as e:
        log_text = f"Błąd czytania logów: {e}"
    return render_template("logs.html", logs=log_text)


@app.route("/testprint", methods=["GET", "POST"])
@login_required
def test_print():
    message = None
    if request.method == "POST":
        success = print_agent.print_test_page()
        message = (
            "Testowy wydruk wysłany." if success else "Błąd testowego wydruku."
        )
    return render_template("testprint.html", message=message)


@app.route("/test", methods=["GET", "POST"])
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


@app.errorhandler(404)
def handle_404(error):
    """Render custom page for 404 errors."""
    return render_template("404.html"), 404


@app.errorhandler(500)
def handle_500(error):
    """Render custom page for internal server errors."""
    return render_template("500.html"), 500


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init_db":
        init_db()
    else:
        ensure_db_initialized()
        app.run(host="0.0.0.0", port=80, debug=settings.FLASK_DEBUG)
