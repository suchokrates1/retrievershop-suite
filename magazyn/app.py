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
from datetime import datetime, timezone
import os
import sys
import uuid
from werkzeug.security import check_password_hash
from collections import OrderedDict
from typing import Optional

from requests.exceptions import HTTPError, RequestException

from .models import User, Thread, Message
from .forms import LoginForm
from sqlalchemy.orm import joinedload

from .db import (
    get_session,
    init_db,
    reset_db,
    record_purchase,
    consume_stock,
)
from .sales import _sales_keys
from .auth import login_required
from . import print_agent, allegro_api
from .allegro import ALLEGRO_AUTHORIZATION_URL
from .allegro_token_refresher import token_refresher
from .env_info import ENV_INFO
from .config import settings
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


def _serialize_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return str(value)
    except Exception:  # pragma: no cover - defensive
        return None


def _parse_iso_timestamp(raw_value):
    if isinstance(raw_value, datetime):
        return raw_value
    if not raw_value:
        return datetime.utcnow()
    value = str(raw_value).strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.utcnow()
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _message_preview(text: Optional[str], limit: int = 160) -> str:
    if not text:
        return ""
    condensed = " ".join(str(text).strip().split())
    if len(condensed) <= limit:
        return condensed
    return condensed[: max(limit - 3, 0)].rstrip() + "..."


def _latest_message(thread: Thread) -> Optional[Message]:
    messages = getattr(thread, "messages", None) or []
    if not messages:
        return None
    return max(messages, key=lambda msg: msg.created_at or datetime.min)


def _thread_payload(thread: Thread, last_message: Optional[Message] = None) -> dict:
    last_message = last_message or _latest_message(thread)
    return {
        "id": thread.id,
        "title": thread.title,
        "author": thread.author,
        "type": thread.type,
        "read": bool(thread.read),
        "last_message_at": _serialize_dt(thread.last_message_at),
        "last_message_iso": _serialize_dt(thread.last_message_at),
        "last_message_preview": _message_preview(
            getattr(last_message, "content", None)
        ),
        "last_message_author": getattr(last_message, "author", thread.author),
    }


@bp.app_context_processor
def inject_current_year():
    with get_session() as db:
        unread_count = db.query(Thread).filter_by(read=False).count()
    return {"current_year": datetime.now().year, "unread_count": unread_count}


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
        db_path = settings.DB_PATH
        if os.path.isdir(db_path):
            logger = (app_obj or current_app).logger
            logger.error(
                (
                    f"Database path {db_path} is a directory. "
                    "Please fix the mount."
                )
            )
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.")
            raise SystemExit(1)
        if os.path.exists(db_path) and not os.path.isfile(db_path):
            logger = (app_obj or current_app).logger
            logger.error(f"Database path {db_path} is not a file.")
            if has_request_context():
                flash("Błąd konfiguracji bazy danych.")
            raise SystemExit(1)

        # Always run table creation so new tables appear automatically.
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


@bp.route("/discussions")
@login_required
def discussions():
    with get_session() as db:
        threads_from_db = (
            db.query(Thread)
            .options(joinedload(Thread.messages))
            .order_by(Thread.last_message_at.desc(), Thread.title.asc())
            .all()
        )
        threads = [
            _thread_payload(thread, last_message=_latest_message(thread))
            for thread in threads_from_db
        ]

    can_reply = bool(getattr(settings, "ALLEGRO_ACCESS_TOKEN", None))
    autoresponder_enabled = bool(
        getattr(settings, "ALLEGRO_AUTORESPONDER_ENABLED", False)
    )

    return render_template(
        "discussions.html",
        threads=threads,
        username=session.get("username"),
        can_reply=can_reply,
        autoresponder_enabled=autoresponder_enabled,
    )


@bp.route("/discussions/<string:thread_id>/read", methods=["POST"])
@login_required
def mark_as_read(thread_id):
    with get_session() as db:
        thread = db.query(Thread).filter_by(id=thread_id).first()
        if thread:
            thread.read = True
            db.flush()
            return {"success": True, "thread": _thread_payload(thread)}
        return {"success": False}, 404


@bp.route("/discussions/<thread_id>")
@login_required
def get_messages(thread_id):
    with get_session() as db:
        thread = (
            db.query(Thread)
            .options(joinedload(Thread.messages))
            .filter_by(id=thread_id)
            .first()
        )
        if not thread:
            return {"error": "Thread not found"}, 404

        ordered_messages = sorted(
            thread.messages,
            key=lambda message: message.created_at or datetime.min,
        )
        thread_payload = _thread_payload(
            thread,
            last_message=ordered_messages[-1] if ordered_messages else None,
        )
        return {
            "thread": thread_payload,
            "messages": [
                {
                    "id": message.id,
                    "author": message.author,
                    "content": message.content,
                    "created_at": _serialize_dt(message.created_at),
                }
                for message in ordered_messages
            ],
        }


@bp.route("/discussions/create", methods=["POST"])
@login_required
def create_thread():
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    thread_type = (payload.get("type") or "").strip()
    initial_message = (payload.get("message") or "").strip()

    if not title or not thread_type or not initial_message:
        return {"error": "Wszystkie pola są wymagane."}, 400

    now = datetime.utcnow()

    with get_session() as db:
        new_thread = Thread(
            id=str(uuid.uuid4()),
            title=title,
            author=session["username"],
            type=thread_type,
            read=True,
            last_message_at=now,
        )
        db.add(new_thread)

        new_message = Message(
            id=str(uuid.uuid4()),
            thread_id=new_thread.id,
            author=session["username"],
            content=initial_message,
            created_at=now,
        )
        db.add(new_message)
        db.flush()

        thread_payload = _thread_payload(new_thread, last_message=new_message)

        return {
            "id": new_thread.id,
            "thread": thread_payload,
            "message": {
                "id": new_message.id,
                "author": new_message.author,
                "content": new_message.content,
                "created_at": _serialize_dt(new_message.created_at),
            },
        }, 201


@bp.route("/discussions/<string:thread_id>/send", methods=["POST"])
@login_required
def send_message(thread_id):
    payload = request.get_json(silent=True) or {}
    content = (payload.get("content") or "").strip()
    if not content:
        return {"error": "Treść wiadomości nie może być pusta."}, 400

    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {
            "error": "Brak skonfigurowanego tokenu Allegro. Zaktualizuj ustawienia integracji.",
        }, 400

    with get_session() as db:
        thread = db.query(Thread).filter_by(id=thread_id).first()
        if not thread:
            return {"error": "Thread not found"}, 404

        try:
            response = allegro_api.send_thread_message(token, thread_id, content)
        except HTTPError as exc:  # pragma: no cover - relies on Allegro API
            current_app.logger.exception(
                "Nie udało się wysłać wiadomości do Allegro dla wątku %s", thread_id
            )
            status_code = getattr(getattr(exc, "response", None), "status_code", 0)
            if status_code == 401:
                message = "Token Allegro wygasł. Odśwież integrację i spróbuj ponownie."
            else:
                message = "Allegro odrzuciło wiadomość. Sprawdź logi i spróbuj ponownie."
            return {"error": message}, 502
        except RequestException:
            current_app.logger.exception(
                "Błąd sieci podczas wysyłania wiadomości Allegro dla wątku %s",
                thread_id,
            )
            return {
                "error": "Nie udało się połączyć z Allegro. Spróbuj ponownie.",
            }, 502

        created_at_dt = _parse_iso_timestamp(
            response.get("createdAt") or response.get("created_at")
        )
        message_id = str(response.get("id") or uuid.uuid4())

        new_message = Message(
            id=message_id,
            thread_id=thread_id,
            author=session["username"],
            content=content,
            created_at=created_at_dt,
        )
        db.add(new_message)
        thread.last_message_at = created_at_dt
        thread.read = True
        db.flush()

        payload = {
            "id": new_message.id,
            "author": new_message.author,
            "content": new_message.content,
            "created_at": _serialize_dt(new_message.created_at),
            "thread": _thread_payload(thread, last_message=new_message),
        }
        return payload


@bp.app_errorhandler(404)
def handle_404(error):
    """Render custom page for 404 errors."""
    return render_template("404.html"), 404


@bp.app_errorhandler(500)
def handle_500(error):
    """Render custom page for internal server errors."""
    return render_template("500.html"), 500


