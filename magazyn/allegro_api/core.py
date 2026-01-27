"""
Podstawowe funkcje HTTP dla Allegro API.

Zawiera: retry logic, rate limiting, error handling.
"""
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests
from requests import Response
from requests.exceptions import HTTPError, RequestException

from ..env_tokens import clear_allegro_tokens, update_allegro_tokens
from ..settings_store import SettingsPersistenceError, settings_store
from ..metrics import (
    ALLEGRO_API_ERRORS_TOTAL,
    ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS,
    ALLEGRO_API_RETRIES_TOTAL,
)


AUTH_URL = "https://allegro.pl/auth/oauth/token"
API_BASE_URL = "https://api.allegro.pl"
DEFAULT_TIMEOUT = 10
MAX_RETRY_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 30


def _safe_int(value) -> Optional[int]:
    """Bezpieczna konwersja na int."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _force_clear_allegro_tokens() -> None:
    """Wyczysc tokeny Allegro bezpośrednio z settings store."""
    settings_store.update(
        {
            "ALLEGRO_ACCESS_TOKEN": None,
            "ALLEGRO_REFRESH_TOKEN": None,
            "ALLEGRO_TOKEN_EXPIRES_IN": None,
            "ALLEGRO_TOKEN_METADATA": None,
        }
    )


def _parse_retry_after(value: Optional[str]) -> float:
    """Parsuj nagłówek Retry-After."""
    if not value:
        return 0.0
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((dt - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _parse_rate_limit_reset(value: Optional[str]) -> float:
    """Parsuj nagłówek X-RateLimit-Reset."""
    if not value:
        return 0.0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((dt - datetime.now(timezone.utc)).total_seconds(), 0.0)
    now = time.time()
    if seconds > now + 1:
        return max(seconds - now, 0.0)
    return max(seconds, 0.0)


def _rate_limit_delay(headers) -> float:
    """Oblicz opóźnienie wynikające z rate limitingu."""
    if not headers:
        return 0.0
    delay = _parse_retry_after(headers.get("Retry-After"))
    if delay:
        return delay
    remaining = headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        try:
            if float(remaining) > 0:
                return 0.0
        except (TypeError, ValueError):
            pass
    delay = _parse_rate_limit_reset(headers.get("X-RateLimit-Reset"))
    if delay:
        return delay
    return 0.0


def _sleep_for_limit(delay: float, endpoint: str) -> None:
    """Uśpij z metryką rate limitingu."""
    if delay <= 0:
        return
    ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS.labels(endpoint=endpoint).inc(delay)
    time.sleep(delay)


def _should_retry(status_code: int) -> bool:
    """Sprawdź czy należy ponowić żądanie."""
    return status_code == 429 or 500 <= status_code < 600


def _respect_rate_limits(response: Response, endpoint: str) -> None:
    """Respektuj rate limity z odpowiedzi."""
    headers = getattr(response, "headers", None)
    delay = _rate_limit_delay(headers)
    if delay > 0:
        _sleep_for_limit(delay, endpoint)


def _request_with_retry(method, url: str, *, endpoint: str, **kwargs) -> Response:
    """Wykonaj żądanie HTTP z retry logic i rate limiting."""
    attempt = 0
    backoff = 1.0
    while True:
        attempt += 1
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        try:
            response = method(url, **kwargs)
        except RequestException:
            ALLEGRO_API_ERRORS_TOTAL.labels(endpoint=endpoint, status="exception").inc()
            if attempt >= MAX_RETRY_ATTEMPTS:
                raise
            ALLEGRO_API_RETRIES_TOTAL.labels(endpoint=endpoint).inc()
            delay = min(backoff, MAX_BACKOFF_SECONDS)
            _sleep_for_limit(delay, endpoint)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        status_code = getattr(response, "status_code", None) or 0
        if _should_retry(status_code):
            ALLEGRO_API_ERRORS_TOTAL.labels(
                endpoint=endpoint, status=str(status_code)
            ).inc()
            if attempt < MAX_RETRY_ATTEMPTS:
                ALLEGRO_API_RETRIES_TOTAL.labels(endpoint=endpoint).inc()
                delay = _rate_limit_delay(response.headers)
                if delay <= 0:
                    delay = min(backoff, MAX_BACKOFF_SECONDS)
                _sleep_for_limit(delay, endpoint)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

        try:
            response.raise_for_status()
        except HTTPError:
            ALLEGRO_API_ERRORS_TOTAL.labels(
                endpoint=endpoint, status=str(status_code)
            ).inc()
            raise

        _respect_rate_limits(response, endpoint)
        return response


def _describe_token(token: Optional[str]) -> str:
    """Opisz token (maskując środek)."""
    if not token:
        return "brak"
    if len(token) <= 8:
        return token
    return f"{token[:4]}...{token[-4:]}"


def _extract_allegro_error_details(response) -> dict:
    """Wyciągnij szczegóły błędu z odpowiedzi Allegro."""
    details = {}
    if response is None:
        return details

    payload = None
    try:
        payload = response.json()
    except ValueError:
        text = getattr(response, "text", None)
        if text:
            snippet = str(text).strip()
            if snippet:
                details["body"] = snippet[:500]
        return details

    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list):
            for entry in errors:
                if not isinstance(entry, dict):
                    continue
                code = entry.get("code") or entry.get("error")
                if code and "error_code" not in details:
                    details["error_code"] = str(code)
                message = entry.get("message") or entry.get("userMessage")
                if message and "error_message" not in details:
                    details["error_message"] = str(message)
                details_value = entry.get("details") or entry.get("path")
                if details_value and "error_details" not in details:
                    details["error_details"] = str(details_value)
                if "error_code" in details and "error_message" in details:
                    break
        else:
            code = payload.get("code") or payload.get("error")
            if code:
                details["error_code"] = str(code)
            message = payload.get("message") or payload.get("error_description")
            if message:
                details["error_message"] = str(message)

    return details
