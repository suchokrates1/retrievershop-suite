"""Czyste helpery domenowe dla dyskusji Allegro."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..models.messages import Message, Thread


def serialize_dt(value) -> Optional[str]:
    """Serializuj datetime do formatu ISO."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return None


def parse_iso_timestamp(raw_value) -> datetime:
    """Parsuj znacznik czasu ISO do datetime bez strefy."""
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


def message_preview(text: Optional[str], limit: int = 160) -> str:
    """Zwroc skrocony podglad wiadomosci."""
    if not text:
        return ""
    condensed = " ".join(str(text).strip().split())
    if len(condensed) <= limit:
        return condensed
    return condensed[: max(limit - 3, 0)].rstrip() + "..."


def latest_message(thread: Thread) -> Optional[Message]:
    """Zwroc najnowsza wiadomosc w watku."""
    messages = getattr(thread, "messages", None) or []
    if not messages:
        return None
    return max(messages, key=lambda msg: msg.created_at or datetime.min)


def thread_payload(thread: Thread, last_message: Optional[Message] = None) -> dict:
    """Zbuduj payload watku dla odpowiedzi API."""
    last_message = last_message or latest_message(thread)
    return {
        "id": thread.id,
        "title": thread.title,
        "author": thread.author,
        "type": thread.type,
        "read": bool(thread.read),
        "last_message_at": serialize_dt(thread.last_message_at),
        "last_message_iso": serialize_dt(thread.last_message_at),
        "last_message_preview": message_preview(getattr(last_message, "content", None)),
        "last_message_author": getattr(last_message, "author", thread.author),
    }


def get_thread_title(thread: dict) -> str:
    """Zbuduj tytul watku z odpowiedzi Messaging API."""
    interlocutor = thread.get("interlocutor", {})
    login = interlocutor.get("login", "Nieznany")
    return f"Rozmowa z {login}"


def get_thread_author(thread: dict) -> str:
    """Pobierz autora watku z odpowiedzi Messaging API."""
    interlocutor = thread.get("interlocutor", {})
    return interlocutor.get("login", "Nieznany")


def get_message_author(message: dict) -> str:
    """Pobierz autora wiadomosci z uwzglednieniem roli."""
    author = message.get("author", {})
    role = author.get("role", "")
    login = author.get("login", "")
    if role == "BUYER":
        return login or "Kupujący"
    if role == "SELLER":
        return login or "Ty"
    return login or "System"


def get_issue_title(issue: dict) -> str:
    """Zbuduj tytul dyskusji lub reklamacji."""
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


def get_issue_type_pl(issue_type: str) -> str:
    """Przetlumacz typ problemu na polska etykiete."""
    type_map = {
        "DISPUTE": "dyskusja",
        "CLAIM": "reklamacja",
    }
    return type_map.get(issue_type, issue_type.lower())


__all__ = [
    "get_issue_title",
    "get_issue_type_pl",
    "get_message_author",
    "get_thread_author",
    "get_thread_title",
    "latest_message",
    "message_preview",
    "parse_iso_timestamp",
    "serialize_dt",
    "thread_payload",
]