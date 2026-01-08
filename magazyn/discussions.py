"""
Moduł obsługujący dyskusje i wiadomości Allegro.
Wydzielony z app.py dla lepszej czytelności.
"""
from datetime import datetime, timezone
import uuid
from typing import Optional

from flask import (
    Blueprint,
    current_app,
    make_response,
    render_template,
    request,
    session,
)
from requests.exceptions import HTTPError, RequestException

from .auth import login_required
from .config import settings
from .db import get_session
from .models import Thread, Message
from . import allegro_api

bp = Blueprint("discussions", __name__)


# =============================================================================
# Helper functions
# =============================================================================

def _serialize_dt(value) -> Optional[str]:
    """Serialize datetime to ISO format string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return None


def _parse_iso_timestamp(raw_value) -> datetime:
    """Parse ISO timestamp string to datetime."""
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
    """Return truncated message preview."""
    if not text:
        return ""
    condensed = " ".join(str(text).strip().split())
    if len(condensed) <= limit:
        return condensed
    return condensed[: max(limit - 3, 0)].rstrip() + "..."


def _latest_message(thread: Thread) -> Optional[Message]:
    """Return the most recent message in a thread."""
    messages = getattr(thread, "messages", None) or []
    if not messages:
        return None
    return max(messages, key=lambda msg: msg.created_at or datetime.min)


def _thread_payload(thread: Thread, last_message: Optional[Message] = None) -> dict:
    """Build thread payload for API response."""
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


def _get_thread_title(thread: dict) -> str:
    """Generate thread title from Messaging API response."""
    interlocutor = thread.get("interlocutor", {})
    login = interlocutor.get("login", "Nieznany")
    return f"Rozmowa z {login}"


def _get_thread_author(thread: dict) -> str:
    """Get thread author from Messaging API response."""
    interlocutor = thread.get("interlocutor", {})
    return interlocutor.get("login", "Nieznany")


def _get_message_author(message: dict) -> str:
    """Get message author with role context."""
    author = message.get("author", {})
    role = author.get("role", "")
    login = author.get("login", "")
    if role == "BUYER":
        return login or "Kupujący"
    elif role == "SELLER":
        return login or "Ty"
    return login or "System"


def _get_issue_title(issue: dict) -> str:
    """Generate title for dispute/claim."""
    issue_type = issue.get("type")
    subject = issue.get("subject") or ""
    buyer_login = issue.get("buyer", {}).get("login", "Nieznany")
    
    if issue_type == "DISPUTE":
        prefix = "Dyskusja"
    elif issue_type == "CLAIM":
        prefix = "Reklamacja"
    else:
        prefix = "Problem"
    
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
    """Convert issue type to Polish."""
    type_map = {
        "DISPUTE": "dyskusja",
        "CLAIM": "reklamacja",
    }
    return type_map.get(issue_type, issue_type.lower())


# =============================================================================
# Routes
# =============================================================================

@bp.route("/discussions")
@login_required
def discussions_list():
    """Display list of all discussions from Allegro."""
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    can_reply = bool(token)
    autoresponder_enabled = bool(
        getattr(settings, "ALLEGRO_AUTORESPONDER_ENABLED", False)
    )
    
    threads = []
    error_message = None
    
    if not token:
        try:
            with get_session() as db:
                db_threads = (
                    db.query(Thread)
                    .order_by(Thread.last_message_at.desc())
                    .all()
                )
                for thread in db_threads:
                    last_msg = thread.messages[-1] if thread.messages else None
                    last_at = last_msg.created_at if last_msg else thread.last_message_at
                    threads.append(
                        {
                            "id": thread.id,
                            "title": thread.title,
                            "author": thread.author,
                            "type": thread.type,
                            "read": thread.read,
                            "last_message_at": last_at,
                            "last_message_iso": last_at.isoformat() if last_at else None,
                            "last_message_preview": (last_msg.content if last_msg else ""),
                            "last_message_author": last_msg.author if last_msg else thread.author,
                            "source": "local",
                        }
                    )
        except Exception as exc:
            current_app.logger.warning("Nie udało się odczytać lokalnych dyskusji: %s", exc)

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
            for thread in messaging_threads:
                last_msg_time = thread.get("lastMessageDateTime")
                
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
            
            threads.sort(key=lambda t: t.get("last_message_at") or "", reverse=True)
            
        except HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", 0)
            if status_code == 401:
                refresh_token = getattr(settings, "ALLEGRO_REFRESH_TOKEN", None)
                if refresh_token:
                    try:
                        from .env_tokens import update_allegro_tokens
                        current_app.logger.info("Próba odświeżenia tokena Allegro...")
                        new_tokens = allegro_api.refresh_token(refresh_token)
                        
                        update_allegro_tokens(
                            access_token=new_tokens.get("access_token"),
                            refresh_token=new_tokens.get("refresh_token"),
                            expires_in=new_tokens.get("expires_in"),
                        )
                        
                        current_app.logger.info("Token Allegro odświeżony i zapisany pomyślnie")
                        return discussions_list()
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


@bp.route("/discussions/<string:thread_id>/read", methods=["POST"])
@login_required
def mark_as_read(thread_id):
    """Mark thread as read."""
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
    """
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401
    
    thread_source = request.args.get("source", "messaging")
    
    def try_fetch_messages(source_type):
        """Pobierz wiadomości z odpowiedniego API."""
        current_app.logger.debug(
            f"Fetching {source_type} messages for thread {thread_id}"
        )
        
        if source_type == "issue":
            data = allegro_api.fetch_discussion_chat(token, thread_id)
            raw_messages = data.get("chat", [])
        else:
            data = allegro_api.fetch_thread_messages(token, thread_id)
            raw_messages = data.get("messages", [])
        
        current_app.logger.info(
            f"Got {len(raw_messages)} messages from {source_type} API for thread {thread_id}"
        )
        
        if len(raw_messages) == 0:
            current_app.logger.warning(
                f"Thread {thread_id} has 0 messages. Full response keys: {list(data.keys())}"
            )
        
        messages = []
        for msg in raw_messages:
            author_data = msg.get("author", {})
            
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
        messages, actual_source = try_fetch_messages(thread_source)
        
    except HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", 0)
        response_obj = getattr(exc, "response", None)
        
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
        
        # Retry logic for 422 errors
        if status_code == 422 and thread_source == "messaging":
            try:
                current_app.logger.info(f"Thread {thread_id} returned 422 as messaging, trying as issue...")
                messages, actual_source = try_fetch_messages("issue")
            except HTTPError as retry_exc:
                retry_status = getattr(getattr(retry_exc, "response", None), "status_code", 0)
                if retry_status == 404:
                    return {"error": "Wątek nie znaleziony w żadnym API"}, 404
                current_app.logger.exception("Retry as issue also failed")
                return {"error": "Nie udało się pobrać wiadomości z żadnego API"}, 502
        
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
    """Create a new local discussion thread."""
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
    Wysyła wiadomość do wątku Allegro.
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
        if thread_source == "issue":
            response = allegro_api.send_discussion_message(
                token, thread_id, content, attachment_ids=attachment_ids
            )
        else:
            response = allegro_api.send_thread_message(
                token, thread_id, content, attachment_ids=attachment_ids
            )
            
    except HTTPError as exc:
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
                db.flush()

                payload = {
                    "id": new_message.id,
                    "author": new_message.author,
                    "content": new_message.content,
                    "created_at": _serialize_dt(new_message.created_at),
                    "thread": _thread_payload(thread, last_message=new_message),
                }
                
                broadcast_new_message(thread_id, payload)
                
                return payload
    except Exception as e:
        current_app.logger.warning("Nie udało się zapisać wiadomości w cache: %s", e)
    
    # Fallback response if local cache failed
    return {
        "id": message_id,
        "author": session.get("username", "Ty"),
        "content": content,
        "created_at": _serialize_dt(created_at_dt),
    }


@bp.route("/discussions/attachments/upload", methods=["POST"])
@login_required
def upload_attachment():
    """
    Przesyła załącznik do Allegro.
    """
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401
    
    if 'file' not in request.files:
        return {"error": "Brak pliku"}, 400
    
    file = request.files['file']
    if file.filename == '':
        return {"error": "Nie wybrano pliku"}, 400
    
    source = request.form.get('source', 'messaging')
    
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
        file_content = file.read()
        filename = file.filename
        
        if source == "issue":
            if len(file_content) > 2097152:
                return {"error": "Plik za duży (max 2MB dla dyskusji/reklamacji)"}, 400
            attachment_id = allegro_api.upload_issue_attachment_complete(
                token, filename, file_content, content_type
            )
        else:
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
    """
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401
    
    source = request.args.get('source', 'messaging')
    
    try:
        if source == "issue":
            file_content = allegro_api.download_issue_attachment(token, attachment_id)
        else:
            file_content = allegro_api.download_attachment(token, attachment_id)
        
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
