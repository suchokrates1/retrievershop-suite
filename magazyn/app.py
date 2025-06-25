from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
from datetime import datetime
from werkzeug.security import check_password_hash
from dotenv import load_dotenv, dotenv_values
from collections import OrderedDict
from pathlib import Path

from .models import User, Settings, Product

from .db import (
    get_session,
    init_db,
    register_default_user,
    record_purchase,
    consume_stock,
)
from .products import (
    bp as products_bp,
    add_item,
    update_quantity,
    delete_item,
    edit_item,
    items,
    barcode_scan,
    barcode_scan_page,
    export_products,
    import_products,
    add_delivery,
)
from .history import bp as history_bp, print_history
from .auth import login_required
from . import print_agent
from __init__ import DB_PATH

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
EXAMPLE_PATH = ROOT_DIR / ".env.example"


load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "default_secret_key")

app.register_blueprint(products_bp)
app.register_blueprint(history_bp)


@app.context_processor
def inject_current_year():
    return {"current_year": datetime.now().year}


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


@app.route("/")
@login_required
def home():
    username = session["username"]
    return render_template("home.html", username=username)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        with get_session() as db:
            user = db.query(User).filter_by(username=username).first()

        if user and check_password_hash(user["password"], password):
            session["username"] = username
            return redirect(url_for("home"))
        else:
            flash("Niepoprawna nazwa użytkownika lub hasło")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    keys = ["PRINTER_NAME", "CUPS_SERVER", "CUPS_PORT"]
    if request.method == "POST":
        with get_session() as db:
            for key in keys:
                value = request.form.get(key, "")
                obj = db.get(Settings, key)
                if not obj:
                    obj = Settings(key=key)
                obj.value = value
                db.add(obj)
        flash("Zapisano ustawienia.")
        return redirect(url_for("settings"))
    with get_session() as db:
        values = {key: "" for key in keys}
        rows = db.query(Settings).filter(Settings.key.in_(keys)).all()
        for row in rows:
            values[row.key] = row.value
    return render_template("settings.html", settings=values)


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
        message = "Testowy wydruk wysłany." if success else "Błąd testowego wydruku."
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


if __name__ == "__main__":
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
