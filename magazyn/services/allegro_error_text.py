"""Ludzkie komunikaty z błędów Allegro Shipment Management."""

from __future__ import annotations

import re
from typing import Any

_EXACT_PL = {
    "the contact number must be a polish mobile number": (
        "Numer telefonu musi być polskim numerem komórkowym."
    ),
    "invalid phone number": "Numer telefonu jest nieprawidłowy.",
    "phone number is invalid": "Numer telefonu jest nieprawidłowy.",
    "the provided phone number is invalid": "Numer telefonu jest nieprawidłowy.",
    "postal code is invalid": "Kod pocztowy jest nieprawidłowy.",
    "invalid postal code": "Kod pocztowy jest nieprawidłowy.",
    "building number is required": "Brak numeru budynku w adresie.",
    "street is required": "Brak ulicy w adresie.",
    "receiver name is required": "Brak imienia i nazwiska odbiorcy.",
    "pickup point is required": "Brak punktu odbioru.",
    "point not found": "Nie znaleziono punktu odbioru.",
}

_CONTAINS_PL = (
    (
        "polish mobile number",
        "Numer telefonu musi być polskim numerem komórkowym.",
    ),
)

_ENGLISH_WORDS = {
    "must",
    "invalid",
    "required",
    "should",
    "cannot",
    "can't",
    "the",
    "number",
    "phone",
    "contact",
    "value",
    "parameter",
    "error",
    "failed",
    "exceeded",
    "missing",
    "empty",
    "not",
    "found",
    "too",
}

_POLISH_CHARS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_CREATION_PREFIX = "Blad tworzenia przesylki: "


def humanize_allegro_errors(errors: list[Any]) -> str:
    """Złóż jedno zdanie po polsku z listy błędów Allegro."""
    parts: list[str] = []
    for error in errors:
        text = humanize_allegro_error(error)
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


def humanize_allegro_error(error: Any) -> str:
    """Przetłumacz jeden błąd Allegro na zdanie dla człowieka."""
    if not isinstance(error, dict):
        raw = str(error or "").strip()
        return _as_human_sentence(raw) if raw else ""

    message = str(error.get("message") or "").strip()
    user_message = str(error.get("userMessage") or "").strip()
    for candidate in (user_message, message):
        translated = _translate(candidate)
        if translated:
            return translated

    for candidate in (user_message, message):
        if candidate and (_has_polish_chars(candidate) or not _looks_english(candidate)):
            return _as_human_sentence(candidate)

    raw = user_message or message
    if raw:
        return f"Allegro odrzuciło etykietę: {raw.rstrip('.')}."
    return "Allegro odrzuciło utworzenie etykiety."


def human_reason_from_exception(exc: BaseException) -> str:
    """Wyciągnij ludzki powód z wyjątku tworzenia przesyłki, albo pusty string."""
    errors = allegro_errors_from_exception(exc)
    if errors:
        return humanize_allegro_errors(errors)

    text = str(exc).strip()
    if text.startswith(_CREATION_PREFIX):
        return humanize_allegro_errors([{"message": text[len(_CREATION_PREFIX):].strip()}])
    return ""


def allegro_errors_from_exception(exc: BaseException) -> list[dict[str, Any]]:
    """Zbierz strukture błędów Allegro z wyjątku komendy albo odpowiedzi HTTP."""
    own_errors = getattr(exc, "errors", None)
    if isinstance(own_errors, list) and own_errors:
        return [item for item in own_errors if isinstance(item, dict)]

    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.json() or {}
        except Exception:
            body = {}
        errors = body.get("errors") if isinstance(body, dict) else None
        if isinstance(errors, list) and errors:
            return [item for item in errors if isinstance(item, dict)]
    return []


def _translate(text: str) -> str:
    key = _normalize(text)
    if not key:
        return ""
    exact = _EXACT_PL.get(key)
    if exact:
        return exact
    for needle, polish in _CONTAINS_PL:
        if needle in key:
            return polish
    return ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(".").strip()).casefold()


def _has_polish_chars(text: str) -> bool:
    return any(char in _POLISH_CHARS for char in text)


def _looks_english(text: str) -> bool:
    words = set(re.findall(r"[a-z']+", text.casefold()))
    return bool(words & _ENGLISH_WORDS)


def _as_human_sentence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}."
    return cleaned


__all__ = [
    "allegro_errors_from_exception",
    "human_reason_from_exception",
    "humanize_allegro_error",
    "humanize_allegro_errors",
]
