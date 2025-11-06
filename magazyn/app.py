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
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    can_reply = bool(token)
    autoresponder_enabled = bool(
        getattr(settings, "ALLEGRO_AUTORESPONDER_ENABLED", False)
    )
    
    threads = []
    error_message = None
    
    if token:
        try:
            # Pobierz wątki z Centrum Wiadomości Allegro
            messaging_data = allegro_api.fetch_message_threads(token)
            messaging_threads = messaging_data.get("threads", [])
            
            # Pobierz dyskusje i reklamacje
            try:
                issues_data = allegro_api.fetch_discussion_issues(token)
                issues = issues_data.get("issues", [])
            except Exception as e:
                current_app.logger.warning("Nie udało się pobrać dyskusji: %s", e)
                issues = []
            
            # Konwertuj wątki z Centrum Wiadomości
            # API zwraca: {id, read, lastMessageDateTime, interlocutor}
            for thread in messaging_threads:
                last_msg_time = thread.get("lastMessageDateTime")
                
                # POMIŃ puste wątki (brak lastMessageDateTime = brak wiadomości)
                if not last_msg_time:
                    current_app.logger.debug(
                        f"Skipping empty thread {thread.get('id')} (no lastMessageDateTime)"
                    )
                    continue
                
                threads.append({
                    "id": thread.get("id"),
                    "title": _get_thread_title(thread),
                    "author": _get_thread_author(thread),
                    "type": "wiadomość",
                    "read": thread.get("read", False),
                    "last_message_at": last_msg_time,
                    "last_message_iso": last_msg_time,
                    "last_message_preview": "Kliknij aby zobaczyć wiadomości",
                    "last_message_author": "",
                    "source": "messaging",
                })
            
            # Konwertuj dyskusje i reklamacje
            for issue in issues:
                chat = issue.get("chat", {})
                last_msg = chat.get("lastMessage", {})
                initial_msg = chat.get("initialMessage", {})
                threads.append({
                    "id": issue.get("id"),
                    "title": _get_issue_title(issue),
                    "author": issue.get("buyer", {}).get("login", "Nieznany"),
                    "type": _get_issue_type_pl(issue.get("type")),
                    "read": last_msg.get("status") != "NEW",
                    "last_message_at": last_msg.get("createdAt"),
                    "last_message_iso": last_msg.get("createdAt"),
                    "last_message_preview": _message_preview(initial_msg.get("text")),
                    "last_message_author": initial_msg.get("author", {}).get("login", ""),
                    "source": "issue",
                })
            
            # Sortuj po dacie ostatniej wiadomości
            threads.sort(key=lambda t: t.get("last_message_at") or "", reverse=True)
            
        except HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", 0)
            if status_code == 401:
                # Token wygasł - spróbuj odświeżyć
                refresh_token = getattr(settings, "ALLEGRO_REFRESH_TOKEN", None)
                if refresh_token:
                    try:
                        from .env_tokens import update_allegro_tokens
                        current_app.logger.info("Próba odświeżenia tokena Allegro...")
                        new_tokens = allegro_api.refresh_token(refresh_token)
                        
                        # Zapisz tokeny do bazy/env i zaktualizuj settings
                        update_allegro_tokens(
                            access_token=new_tokens.get("access_token"),
                            refresh_token=new_tokens.get("refresh_token"),
                            expires_in=new_tokens.get("expires_in"),
                        )
                        
                        current_app.logger.info("Token Allegro odświeżony i zapisany pomyślnie")
                        # Retry request
                        return discussions()  # Rekurencyjne wywołanie po odświeżeniu
                    except Exception as refresh_exc:
                        current_app.logger.error("Nie udało się odświeżyć tokena: %s", refresh_exc)
                        error_message = "Token Allegro wygasł i nie udało się go odświeżyć. Przejdź do ustawień i autoryzuj ponownie."
                else:
                    error_message = "Token Allegro wygasł. Odśwież autoryzację w ustawieniach."
            else:
                error_message = f"Błąd API Allegro: {status_code}"
            current_app.logger.exception("Błąd pobierania wątków z Allegro")
        except RequestException as exc:
            error_message = "Nie udało się połączyć z Allegro."
            current_app.logger.exception("Błąd sieci podczas pobierania wątków")
    
    return render_template(
        "discussions.html",
        threads=threads,
        username=session.get("username"),
        can_reply=can_reply,
        autoresponder_enabled=autoresponder_enabled,
        error_message=error_message,
    )


def _get_thread_title(thread: dict) -> str:
    """Generuj tytuł wątku z Centrum Wiadomości."""
    interlocutor = thread.get("interlocutor", {})
    login = interlocutor.get("login", "Nieznany")
    return f"Rozmowa z {login}"


def _get_thread_author(thread: dict) -> str:
    """Pobierz autora wątku."""
    interlocutor = thread.get("interlocutor", {})
    return interlocutor.get("login", "Nieznany")


def _get_message_author(message: dict) -> str:
    """Pobierz autora wiadomości."""
    author = message.get("author", {})
    role = author.get("role", "")
    login = author.get("login", "")
    if role == "BUYER":
        return login or "Kupujący"
    elif role == "SELLER":
        return login or "Ty"
    return login or "System"


def _get_issue_title(issue: dict) -> str:
    """Generuj tytuł dla dyskusji/reklamacji."""
    issue_type = issue.get("type")
    subject = issue.get("subject") or ""
    buyer_login = issue.get("buyer", {}).get("login", "Nieznany")
    
    if issue_type == "DISPUTE":
        prefix = "Dyskusja"
    elif issue_type == "CLAIM":
        prefix = "Reklamacja"
    else:
        prefix = "Problem"
    
    # Podmień subject na bardziej czytelny
    subject_map = {
        "NO_REFUND_AFTER_RETURNING_PRODUCT": "brak zwrotu po odesłaniu",
        "DEFECTIVE_PRODUCT": "wadliwy produkt",
        "DIFFERENT_PRODUCT": "inny produkt",
        "DAMAGED_PRODUCT": "uszkodzony produkt",
        "NOT_DELIVERED": "nie dostarczono",
    }
    subject_pl = subject_map.get(subject, subject.lower().replace("_", " "))
    
    return f"{prefix}: {buyer_login} - {subject_pl}" if subject_pl else f"{prefix}: {buyer_login}"


def _get_issue_type_pl(issue_type: str) -> str:
    """Konwertuj typ problemu na polski."""
    type_map = {
        "DISPUTE": "dyskusja",
        "CLAIM": "reklamacja",
    }
    return type_map.get(issue_type, issue_type.lower())


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
    """
    Pobierz wiadomości dla danego wątku.
    
    DWA TYPY API:
    1. Messaging API (/messaging/threads) - zwykłe wiadomości
    2. Issues API (/sale/issues) - dyskusje (DISPUTE) i reklamacje (CLAIM)
    
    Próbujemy oba API, jeśli jedno zwraca 422, sprawdzamy drugie.
    """
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401
    
    # Sprawdź typ wątku z parametru source
    thread_source = request.args.get("source", "messaging")
    
    def try_fetch_messages(source_type):
        """Pobierz wiadomości z odpowiedniego API."""
        current_app.logger.debug(
            f"Fetching {source_type} messages for thread {thread_id}"
        )
        
        if source_type == "issue":
            # Issues API: GET /sale/issues/{issueId}/chat
            data = allegro_api.fetch_discussion_chat(token, thread_id)
            # Odpowiedź: {"chat": [...]}
            raw_messages = data.get("chat", [])
        else:
            # Messaging API: GET /messaging/threads/{threadId}/messages
            data = allegro_api.fetch_thread_messages(token, thread_id)
            # Odpowiedź: {"messages": [...]}
            raw_messages = data.get("messages", [])
        
        current_app.logger.info(
            f"Got {len(raw_messages)} messages from {source_type} API for thread {thread_id}"
        )
        
        # Diagnostyka - jeśli brak wiadomości, zaloguj całą odpowiedź
        if len(raw_messages) == 0:
            current_app.logger.warning(
                f"Thread {thread_id} has 0 messages. Full response keys: {list(data.keys())}"
            )
        
        # Konwertuj format wiadomości
        messages = []
        for msg in raw_messages:
            author_data = msg.get("author", {})
            
            # Pobierz załączniki jeśli istnieją
            attachments = []
            for att in msg.get("attachments", []):
                attachments.append({
                    "id": att.get("id"),
                    "filename": att.get("fileName"),
                    "url": att.get("url"),
                    "mimeType": att.get("mimeType"),
                })
            
            messages.append({
                "id": msg.get("id"),
                "author": author_data.get("login", "System"),
                "author_role": author_data.get("role", ""),
                "content": msg.get("text", ""),
                "created_at": msg.get("createdAt"),
                "attachments": attachments,
            })
        return messages, source_type
    
    try:
        # Próbuj ze wskazanym źródłem
        messages, actual_source = try_fetch_messages(thread_source)
        
    except HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", 0)
        response_obj = getattr(exc, "response", None)
        
        # Loguj szczegóły błędu
        error_details = ""
        if response_obj is not None:
            try:
                error_body = response_obj.json()
                error_details = f" Details: {error_body}"
            except:
                error_details = f" Response text: {response_obj.text[:200]}"
        
        current_app.logger.warning(
            f"HTTP {status_code} for thread {thread_id} as {thread_source}.{error_details}"
        )
        
        # Jeśli 422 i próbowaliśmy messaging, spróbuj issue
        if status_code == 422 and thread_source == "messaging":
            try:
                current_app.logger.info(f"Thread {thread_id} returned 422 as messaging, trying as issue...")
                messages, actual_source = try_fetch_messages("issue")
            except HTTPError as retry_exc:
                retry_status = getattr(getattr(retry_exc, "response", None), "status_code", 0)
                retry_response = getattr(retry_exc, "response", None)
                
                # Loguj szczegóły retry
                retry_details = ""
                if retry_response is not None:
                    try:
                        retry_body = retry_response.json()
                        retry_details = f" Details: {retry_body}"
                    except:
                        retry_details = f" Response: {retry_response.text[:200]}"
                
                current_app.logger.warning(
                    f"Retry as issue also failed: HTTP {retry_status}.{retry_details}"
                )
                
                if retry_status == 404:
                    return {"error": "Wątek nie znaleziony w żadnym API"}, 404
                current_app.logger.exception("Retry as issue also failed")
                return {"error": "Nie udało się pobrać wiadomości z żadnego API"}, 502
        
        # Jeśli 422 i próbowaliśmy issue, spróbuj messaging
        elif status_code == 422 and thread_source == "issue":
            try:
                current_app.logger.info(f"Thread {thread_id} returned 422 as issue, trying as messaging...")
                messages, actual_source = try_fetch_messages("messaging")
            except HTTPError as retry_exc:
                retry_status = getattr(getattr(retry_exc, "response", None), "status_code", 0)
                if retry_status == 404:
                    return {"error": "Wątek nie znaleziony w żadnym API"}, 404
                current_app.logger.exception("Retry as messaging also failed")
                return {"error": "Nie udało się pobrać wiadomości z żadnego API"}, 502
        
        # Inne błędy HTTP
        elif status_code == 401:
            return {"error": "Token wygasł"}, 401
        elif status_code == 404:
            return {"error": "Wątek nie znaleziony"}, 404
        else:
            current_app.logger.exception("Błąd API Allegro przy pobieraniu wiadomości")
            return {"error": f"Błąd API: {status_code}"}, 502
            
    except RequestException:
        current_app.logger.exception("Błąd sieci przy pobieraniu wiadomości")
        return {"error": "Błąd połączenia z Allegro"}, 502
    
    # Sortuj od najstarszej do najnowszej
    messages.sort(key=lambda m: m.get("created_at") or "")
    
    return {
        "thread": {
            "id": thread_id,
            "source": actual_source,
        },
        "messages": messages,
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
    """
    Wysyła wiadomość do wątku.
    
    DWA TYPY API:
    1. Messaging API: POST /messaging/threads/{threadId}/messages
    2. Issues API: POST /sale/issues/{issueId}/message
    """
    from .socketio_extension import broadcast_new_message
    
    payload = request.get_json(silent=True) or {}
    content = (payload.get("content") or "").strip()
    thread_source = (payload.get("source") or "messaging").strip()
    attachment_ids = payload.get("attachments", [])
    
    if not content and not attachment_ids:
        return {"error": "Treść wiadomości lub załącznik są wymagane."}, 400

    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {
            "error": "Brak skonfigurowanego tokenu Allegro. Zaktualizuj ustawienia integracji.",
        }, 400

    try:
        # Wybierz odpowiednie API w zależności od źródła
        if thread_source == "issue":
            # Issues API: POST /sale/issues/{issueId}/message
            response = allegro_api.send_discussion_message(
                token, thread_id, content, attachment_ids=attachment_ids
            )
        else:
            # Messaging API: POST /messaging/threads/{threadId}/messages
            response = allegro_api.send_thread_message(
                token, thread_id, content, attachment_ids=attachment_ids
            )
            
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

    # Opcjonalnie zapisz w lokalnej bazie jako cache
    try:
        with get_session() as db:
            thread = db.query(Thread).filter_by(id=thread_id).first()
            if thread:
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
    except Exception as e:
        # Cache niepowodzenie nie powinno blokować odpowiedzi
        current_app.logger.warning("Nie udało się zapisać wiadomości w cache: %s", e)
        db.flush()

        payload = {
            "id": new_message.id,
            "author": new_message.author,
            "content": new_message.content,
            "created_at": _serialize_dt(new_message.created_at),
            "thread": _thread_payload(thread, last_message=new_message),
        }
        
        # Broadcast to other users via WebSocket
        broadcast_new_message(thread_id, payload)
        
        return payload


@bp.route("/discussions/attachments/upload", methods=["POST"])
@login_required
def upload_attachment():
    """
    Przesyła załącznik do Allegro.
    Oczekuje pliku w FormData pod kluczem 'file'.
    Parametr 'source' określa typ API: 'messaging' (default) lub 'issue'.
    Zwraca ID załącznika gotowego do użycia w wiadomości.
    """
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401
    
    # Sprawdź czy plik został przesłany
    if 'file' not in request.files:
        return {"error": "Brak pliku"}, 400
    
    file = request.files['file']
    if file.filename == '':
        return {"error": "Nie wybrano pliku"}, 400
    
    # Sprawdź typ API (messaging vs issue)
    source = request.form.get('source', 'messaging')
    
    # Sprawdź typ pliku
    allowed_types = {
        'image/png': '.png',
        'image/gif': '.gif',
        'image/bmp': '.bmp',
        'image/tiff': '.tiff',
        'image/jpeg': '.jpg',
        'application/pdf': '.pdf',
    }
    
    content_type = file.content_type
    if content_type not in allowed_types:
        return {
            "error": f"Nieobsługiwany typ pliku: {content_type}. "
                     f"Dozwolone: {', '.join(allowed_types.keys())}"
        }, 400
    
    try:
        # Odczytaj zawartość pliku
        file_content = file.read()
        filename = file.filename
        
        # Prześlij do Allegro (wybierz odpowiednie API)
        if source == "issue":
            # Issues API: max 2MB
            if len(file_content) > 2097152:
                return {"error": "Plik za duży (max 2MB dla dyskusji/reklamacji)"}, 400
            attachment_id = allegro_api.upload_issue_attachment_complete(
                token, filename, file_content, content_type
            )
        else:
            # Messaging API
            attachment_id = allegro_api.upload_attachment_complete(
                token, filename, file_content, content_type
            )
        
        return {
            "id": attachment_id,
            "filename": filename,
            "size": len(file_content),
            "mimeType": content_type,
        }
        
    except HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", 0)
        current_app.logger.exception("Błąd API Allegro przy przesyłaniu załącznika")
        
        if status_code == 401:
            return {"error": "Token wygasł"}, 401
        else:
            return {"error": f"Błąd API: {status_code}"}, 502
    
    except Exception as exc:
        current_app.logger.exception("Błąd przy przesyłaniu załącznika")
        return {"error": "Nie udało się przesłać załącznika"}, 500


@bp.route("/discussions/attachments/<attachment_id>")
@login_required
def download_attachment(attachment_id):
    """
    Pobiera załącznik z Allegro.
    Parametr query 'source' określa typ API: 'messaging' (default) lub 'issue'.
    """
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401
    
    # Sprawdź typ API
    source = request.args.get('source', 'messaging')
    
    try:
        # Pobierz z odpowiedniego API
        if source == "issue":
            file_content = allegro_api.download_issue_attachment(token, attachment_id)
        else:
            file_content = allegro_api.download_attachment(token, attachment_id)
        
        # Zwróć plik jako response
        response = make_response(file_content)
        response.headers['Content-Type'] = 'application/octet-stream'
        response.headers['Content-Disposition'] = f'attachment; filename="{attachment_id}"'
        return response
        
    except HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", 0)
        current_app.logger.exception("Błąd API Allegro przy pobieraniu załącznika")
        
        if status_code == 401:
            return {"error": "Token wygasł"}, 401
        elif status_code == 404:
            return {"error": "Załącznik nie znaleziony"}, 404
        else:
            return {"error": f"Błąd API: {status_code}"}, 502
    
    except Exception as exc:
        current_app.logger.exception("Błąd przy pobieraniu załącznika")
        return {"error": "Nie udało się pobrać załącznika"}, 500


@bp.app_errorhandler(404)
def handle_404(error):
    """Render custom page for 404 errors."""
    return render_template("404.html"), 404


@bp.app_errorhandler(500)
def handle_500(error):
    """Render custom page for internal server errors."""
    return render_template("500.html"), 500


