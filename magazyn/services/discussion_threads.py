"""Budowanie listy dyskusji i lokalnych watkow."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from requests.exceptions import HTTPError, RequestException

from .. import allegro_api
from ..config import settings
from ..db import get_session
from ..domain.discussions import (
    get_issue_title,
    get_issue_type_pl,
    get_thread_author,
    get_thread_title,
    message_preview,
    serialize_dt,
    thread_payload,
)
from ..models.messages import Message, Thread
from ..models.orders import Order

logger = logging.getLogger(__name__)


def build_discussions_context(username: str | None, *, log: logging.Logger | None = None) -> dict:
    """Zbuduj kontekst widoku dyskusji z lokalnego cache albo Allegro API."""
    active_logger = log or logger
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    can_reply = bool(token)
    autoresponder_enabled = bool(getattr(settings, "ALLEGRO_AUTORESPONDER_ENABLED", False))

    threads = []
    error_message = None

    if not token:
        threads = _local_threads(active_logger)
    else:
        threads, error_message = _remote_threads(token, active_logger)

    return {
        "threads": threads,
        "username": username,
        "can_reply": can_reply,
        "autoresponder_enabled": autoresponder_enabled,
        "error_message": error_message,
    }


def mark_thread_as_read(thread_id: str) -> tuple[dict, int]:
    """Oznacz lokalny watek jako przeczytany."""
    with get_session() as db:
        thread = db.query(Thread).filter_by(id=thread_id).first()
        if not thread:
            return {"success": False}, 404
        thread.read = True
        db.flush()
        return {"success": True, "thread": thread_payload(thread)}, 200


def create_local_thread(payload: dict, username: str) -> tuple[dict, int]:
    """Utworz lokalny watek dyskusji i pierwsza wiadomosc."""
    title = (payload.get("title") or "").strip()
    thread_type = (payload.get("type") or "").strip()
    initial_message = (payload.get("message") or "").strip()

    if not title or not thread_type or not initial_message:
        return {"error": "Wszystkie pola są wymagane."}, 400

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with get_session() as db:
        new_thread = Thread(
            id=str(uuid.uuid4()),
            title=title,
            author=username,
            type=thread_type,
            read=True,
            last_message_at=now,
        )
        db.add(new_thread)

        new_message = Message(
            id=str(uuid.uuid4()),
            thread_id=new_thread.id,
            author=username,
            content=initial_message,
            created_at=now,
        )
        db.add(new_message)
        db.flush()

        return {
            "id": new_thread.id,
            "thread": thread_payload(new_thread, last_message=new_message),
            "message": {
                "id": new_message.id,
                "author": new_message.author,
                "content": new_message.content,
                "created_at": serialize_dt(new_message.created_at),
            },
        }, 201


def _local_threads(log: logging.Logger) -> list[dict]:
    threads = []
    try:
        with get_session() as db:
            db_threads = db.query(Thread).order_by(Thread.last_message_at.desc()).all()
            for thread in db_threads:
                last_message = thread.messages[-1] if thread.messages else None
                last_at = last_message.created_at if last_message else thread.last_message_at
                last_iso = last_at.isoformat() if last_at else None
                threads.append(
                    {
                        "id": thread.id,
                        "title": thread.title,
                        "author": thread.author,
                        "type": thread.type,
                        "read": thread.read,
                        "last_message_at": last_iso,
                        "last_message_iso": last_iso,
                        "last_message_preview": last_message.content if last_message else "",
                        "last_message_author": last_message.author if last_message else thread.author,
                        "source": "local",
                    }
                )
    except Exception as exc:
        log.warning("Nie udało się odczytać lokalnych dyskusji: %s", exc)
    return threads


def _remote_threads(token: str, log: logging.Logger) -> tuple[list[dict], str | None]:
    try:
        return _fetch_remote_threads(token, log), None
    except HTTPError as exc:
        return _handle_remote_http_error(exc, log)
    except RequestException:
        log.exception("Błąd sieci podczas pobierania wątków")
        return [], "Nie udało się połączyć z Allegro."


def _fetch_remote_threads(token: str, log: logging.Logger) -> list[dict]:
    messaging_data = allegro_api.fetch_message_threads(token)
    messaging_threads = messaging_data.get("threads", [])

    try:
        issues_data = allegro_api.fetch_discussion_issues(token)
        issues = issues_data.get("issues", [])
    except Exception as exc:
        log.warning("Nie udało się pobrać dyskusji: %s", exc)
        issues = []

    login_to_name = _login_to_customer_name(log)
    threads = []
    threads.extend(_messaging_thread_payloads(messaging_threads, login_to_name, log))
    threads.extend(_issue_thread_payloads(issues, login_to_name))
    threads.sort(key=lambda thread: thread.get("last_message_at") or "", reverse=True)
    return threads


def _handle_remote_http_error(exc: HTTPError, log: logging.Logger) -> tuple[list[dict], str | None]:
    status_code = getattr(getattr(exc, "response", None), "status_code", 0)
    if status_code == 401:
        refresh_token = getattr(settings, "ALLEGRO_REFRESH_TOKEN", None)
        if refresh_token:
            try:
                from ..env_tokens import update_allegro_tokens

                log.info("Próba odświeżenia tokena Allegro...")
                new_tokens = allegro_api.refresh_token(refresh_token)
                update_allegro_tokens(
                    access_token=new_tokens.get("access_token"),
                    refresh_token=new_tokens.get("refresh_token"),
                    expires_in=new_tokens.get("expires_in"),
                )
                log.info("Token Allegro odświeżony i zapisany pomyślnie")
                return _fetch_remote_threads(new_tokens.get("access_token"), log), None
            except Exception as refresh_exc:
                log.error("Nie udało się odświeżyć tokena: %s", refresh_exc)
                return [], "Token Allegro wygasł i nie udało się go odświeżyć. Przejdź do ustawień i autoryzuj ponownie."
        return [], "Token Allegro wygasł. Odśwież autoryzację w ustawieniach."

    log.exception("Błąd pobierania wątków z Allegro")
    return [], f"Błąd API Allegro: {status_code}"


def _login_to_customer_name(log: logging.Logger) -> dict[str, str]:
    try:
        with get_session() as db:
            orders_with_login = (
                db.query(Order.user_login, Order.customer_name)
                .filter(Order.user_login.isnot(None), Order.user_login != "")
                .all()
            )
            return {login: name for login, name in orders_with_login if login and name}
    except Exception as exc:
        log.warning("Blad pobierania nazw klientow: %s", exc)
        return {}


def _messaging_thread_payloads(threads: list[dict], login_to_name: dict[str, str], log) -> list[dict]:
    payloads = []
    for thread in threads:
        last_message_at = thread.get("lastMessageDateTime")
        if not last_message_at:
            log.debug("Skipping empty thread %s (no lastMessageDateTime)", thread.get("id"))
            continue

        author = get_thread_author(thread)
        customer_name = login_to_name.get(author, "")
        payloads.append(
            {
                "id": thread.get("id"),
                "title": customer_name or get_thread_title(thread),
                "author": author,
                "type": "wiadomość",
                "read": thread.get("read", False),
                "last_message_at": last_message_at,
                "last_message_iso": last_message_at,
                "last_message_preview": "",
                "last_message_author": "",
                "customer_name": customer_name,
                "source": "messaging",
            }
        )
    return payloads


def _issue_thread_payloads(issues: list[dict], login_to_name: dict[str, str]) -> list[dict]:
    payloads = []
    for issue in issues:
        chat = issue.get("chat", {})
        last_message = chat.get("lastMessage", {})
        initial_message = chat.get("initialMessage", {})
        issue_author = issue.get("buyer", {}).get("login", "Nieznany")
        payloads.append(
            {
                "id": issue.get("id"),
                "title": get_issue_title(issue),
                "author": issue_author,
                "type": get_issue_type_pl(issue.get("type")),
                "read": last_message.get("status") != "NEW",
                "customer_name": login_to_name.get(issue_author, ""),
                "last_message_at": last_message.get("createdAt"),
                "last_message_iso": last_message.get("createdAt"),
                "last_message_preview": message_preview(initial_message.get("text")),
                "last_message_author": initial_message.get("author", {}).get("login", ""),
                "source": "issue",
            }
        )
    return payloads


__all__ = ["build_discussions_context", "create_local_thread", "mark_thread_as_read"]
