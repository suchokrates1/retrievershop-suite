"""Pobieranie i wysylka wiadomosci w dyskusjach Allegro."""

from __future__ import annotations

import html as html_mod
import logging
import uuid

from requests.exceptions import HTTPError, RequestException

from .. import allegro_api
from ..config import settings
from ..db import get_session
from ..domain.discussions import parse_iso_timestamp, serialize_dt, thread_payload
from ..models.messages import Message, Thread
from ..socketio_extension import broadcast_new_message

logger = logging.getLogger(__name__)


def get_thread_messages_payload(
    thread_id: str,
    *,
    source: str = "messaging",
    log: logging.Logger | None = None,
) -> tuple[dict, int]:
    """Pobierz wiadomosci watku z Messaging API albo Issues API."""
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401

    active_logger = log or logger
    try:
        messages, actual_source = _try_fetch_messages(token, thread_id, source, active_logger)
    except HTTPError as exc:
        return _handle_fetch_http_error(exc, token, thread_id, source, active_logger)
    except RequestException:
        active_logger.exception("Błąd sieci przy pobieraniu wiadomości")
        return {"error": "Błąd połączenia z Allegro"}, 502

    messages.sort(key=lambda message: message.get("created_at") or "")
    return {"thread": {"id": thread_id, "source": actual_source}, "messages": messages}, 200


def send_thread_message_payload(
    thread_id: str,
    payload: dict,
    *,
    username: str,
    log: logging.Logger | None = None,
) -> tuple[dict, int]:
    """Wyslij wiadomosc do Allegro i zapisz ja w lokalnym cache, jesli watek istnieje."""
    active_logger = log or logger
    content = (payload.get("content") or "").strip()
    source = (payload.get("source") or "messaging").strip()
    attachment_ids = payload.get("attachments", [])

    if not content and not attachment_ids:
        return {"error": "Treść wiadomości lub załącznik są wymagane."}, 400

    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {
            "error": "Brak skonfigurowanego tokenu Allegro. Zaktualizuj ustawienia integracji.",
        }, 400

    try:
        if source == "issue":
            response = allegro_api.send_discussion_message(
                token,
                thread_id,
                content,
                attachment_ids=attachment_ids,
            )
        else:
            response = allegro_api.send_thread_message(
                token,
                thread_id,
                content,
                attachment_ids=attachment_ids,
            )
    except HTTPError as exc:
        active_logger.exception("Nie udało się wysłać wiadomości do Allegro dla wątku %s", thread_id)
        status_code = getattr(getattr(exc, "response", None), "status_code", 0)
        if status_code == 401:
            message = "Token Allegro wygasł. Odśwież integrację i spróbuj ponownie."
        else:
            message = "Allegro odrzuciło wiadomość. Sprawdź logi i spróbuj ponownie."
        return {"error": message}, 502
    except RequestException:
        active_logger.exception("Błąd sieci podczas wysyłania wiadomości Allegro dla wątku %s", thread_id)
        return {"error": "Nie udało się połączyć z Allegro. Spróbuj ponownie."}, 502

    return _cache_sent_message(thread_id, content, response, username, active_logger), 200


def _try_fetch_messages(token: str, thread_id: str, source: str, log: logging.Logger) -> tuple[list[dict], str]:
    log.debug("Fetching %s messages for thread %s", source, thread_id)

    if source == "issue":
        data = allegro_api.fetch_discussion_chat(token, thread_id)
        raw_messages = data.get("chat", [])
    else:
        data = allegro_api.fetch_thread_messages(token, thread_id)
        raw_messages = data.get("messages", [])

    log.info("Got %s messages from %s API for thread %s", len(raw_messages), source, thread_id)
    if len(raw_messages) == 0:
        log.warning("Thread %s has 0 messages. Full response keys: %s", thread_id, list(data.keys()))

    return [_message_payload(message) for message in raw_messages], source


def _handle_fetch_http_error(
    exc: HTTPError,
    token: str,
    thread_id: str,
    source: str,
    log: logging.Logger,
) -> tuple[dict, int]:
    status_code = getattr(getattr(exc, "response", None), "status_code", 0)
    log.warning("HTTP %s for thread %s as %s.%s", status_code, thread_id, source, _error_details(exc))

    if status_code == 422:
        retry_source = "issue" if source == "messaging" else "messaging"
        try:
            log.info("Thread %s returned 422 as %s, trying as %s...", thread_id, source, retry_source)
            messages, actual_source = _try_fetch_messages(token, thread_id, retry_source, log)
        except HTTPError as retry_exc:
            retry_status = getattr(getattr(retry_exc, "response", None), "status_code", 0)
            if retry_status == 404:
                return {"error": "Wątek nie znaleziony w żadnym API"}, 404
            log.exception("Retry as %s also failed", retry_source)
            return {"error": "Nie udało się pobrać wiadomości z żadnego API"}, 502
        messages.sort(key=lambda message: message.get("created_at") or "")
        return {"thread": {"id": thread_id, "source": actual_source}, "messages": messages}, 200

    if status_code == 401:
        return {"error": "Token wygasł"}, 401
    if status_code == 404:
        return {"error": "Wątek nie znaleziony"}, 404

    log.exception("Błąd API Allegro przy pobieraniu wiadomości")
    return {"error": f"Błąd API: {status_code}"}, 502


def _message_payload(message: dict) -> dict:
    author_data = message.get("author", {})
    attachments = [
        {
            "id": attachment.get("id"),
            "filename": attachment.get("fileName"),
            "url": attachment.get("url"),
            "mimeType": attachment.get("mimeType"),
        }
        for attachment in message.get("attachments", [])
    ]
    return {
        "id": message.get("id"),
        "author": author_data.get("login", "System"),
        "author_role": author_data.get("role", ""),
        "content": html_mod.unescape(message.get("text", "")),
        "created_at": message.get("createdAt"),
        "attachments": attachments,
    }


def _cache_sent_message(thread_id: str, content: str, response: dict, username: str, log: logging.Logger) -> dict:
    created_at = parse_iso_timestamp(response.get("createdAt") or response.get("created_at"))
    message_id = str(response.get("id") or uuid.uuid4())

    try:
        with get_session() as db:
            thread = db.query(Thread).filter_by(id=thread_id).first()
            if thread:
                new_message = Message(
                    id=message_id,
                    thread_id=thread_id,
                    author=username,
                    content=content,
                    created_at=created_at,
                )
                db.add(new_message)
                thread.last_message_at = created_at
                thread.read = True
                db.flush()

                payload = {
                    "id": new_message.id,
                    "author": new_message.author,
                    "content": new_message.content,
                    "created_at": serialize_dt(new_message.created_at),
                    "thread": thread_payload(thread, last_message=new_message),
                }
                broadcast_new_message(thread_id, payload)
                return payload
    except Exception as exc:
        log.warning("Nie udało się zapisać wiadomości w cache: %s", exc)

    return {
        "id": message_id,
        "author": username or "Ty",
        "content": content,
        "created_at": serialize_dt(created_at),
    }


def _error_details(exc: HTTPError) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        return f" Details: {response.json()}"
    except ValueError:
        return f" Response text: {response.text[:200]}"


__all__ = ["get_thread_messages_payload", "send_thread_message_payload"]
