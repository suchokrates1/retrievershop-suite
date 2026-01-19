import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import requests
from requests import Response
from requests.exceptions import HTTPError, RequestException

from .env_tokens import clear_allegro_tokens, update_allegro_tokens
from .settings_store import SettingsPersistenceError, settings_store
from .metrics import (
    ALLEGRO_API_ERRORS_TOTAL,
    ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS,
    ALLEGRO_API_RETRIES_TOTAL,
)


def _safe_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

AUTH_URL = "https://allegro.pl/auth/oauth/token"
API_BASE_URL = "https://api.allegro.pl"
DEFAULT_TIMEOUT = 10
MAX_RETRY_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 30


def _force_clear_allegro_tokens() -> None:
    """Clear Allegro tokens directly from the settings store (monkeypatch-safe)."""

    settings_store.update(
        {
            "ALLEGRO_ACCESS_TOKEN": None,
            "ALLEGRO_REFRESH_TOKEN": None,
            "ALLEGRO_TOKEN_EXPIRES_IN": None,
            "ALLEGRO_TOKEN_METADATA": None,
        }
    )


def _parse_retry_after(value: Optional[str]) -> float:
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
    if delay <= 0:
        return
    ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS.labels(endpoint=endpoint).inc(delay)
    time.sleep(delay)


def _should_retry(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _respect_rate_limits(response: Response, endpoint: str) -> None:
    headers = getattr(response, "headers", None)
    delay = _rate_limit_delay(headers)
    if delay > 0:
        _sleep_for_limit(delay, endpoint)


def _request_with_retry(method, url: str, *, endpoint: str, **kwargs) -> Response:
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


def get_access_token(client_id: str, client_secret: str, code: str, redirect_uri: Optional[str] = None) -> dict:
    """Obtain an access token and refresh token from Allegro.

    Parameters
    ----------
    client_id : str
        Identifier of the Allegro application.
    client_secret : str
        Secret key for the Allegro application.
    code : str
        Authorization code obtained after user consent.
    redirect_uri : Optional[str]
        Redirect URI used during the authorization request.

    Returns
    -------
    dict
        JSON response containing tokens and expiration data.
    """
    data = {"grant_type": "authorization_code", "code": code}
    if redirect_uri:
        data["redirect_uri"] = redirect_uri

    response = requests.post(
        AUTH_URL, data=data, auth=(client_id, client_secret), timeout=DEFAULT_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def refresh_token(refresh_token: str) -> dict:
    """Refresh the access token using credentials stored in ``settings_store``.

    Both the Allegro client identifier and secret must be persisted in the
    settings store. If either value is missing or cannot be retrieved, a
    ``ValueError`` is raised and the request is not executed.
    """

    def _normalize(value: Optional[str]) -> Optional[str]:
        return value or None

    try:
        store_client_id = _normalize(settings_store.get("ALLEGRO_CLIENT_ID"))
        store_client_secret = _normalize(settings_store.get("ALLEGRO_CLIENT_SECRET"))
    except SettingsPersistenceError as exc:
        raise ValueError(
            "Brak danych uwierzytelniających Allegro. Nie można odczytać ustawień."
        ) from exc

    if not (store_client_id and store_client_secret):
        raise ValueError(
            "Brak danych uwierzytelniających Allegro. Uzupełnij ALLEGRO_CLIENT_ID i "
            "ALLEGRO_CLIENT_SECRET w ustawieniach."
        )

    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    response = requests.post(
        AUTH_URL,
        data=data,
        auth=(store_client_id, store_client_secret),
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def fetch_offers(access_token: str, offset: int = 0, limit: int = 100, **kwargs) -> dict:
    """Fetch offers from Allegro using a valid access token.

    Parameters
    ----------
    access_token : str
        OAuth access token for Allegro API.
    offset : int
        Zero-based offset describing where to start fetching results.
        Defaults to ``0``.
    limit : int
        Number of results to fetch per request. Defaults to ``100``.
    **kwargs
        Additional query parameters.

    Returns
    -------
    dict
        JSON response with the list of offers.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    params = {"offset": offset, "limit": limit, **kwargs}
    url = f"{API_BASE_URL}/sale/offers"

    response = _request_with_retry(
        requests.get,
        url,
        endpoint="offers",
        headers=headers,
        params=params,
    )
    return response.json()


def fetch_discussions(access_token: str) -> dict:
    """Fetch all discussions from Allegro using a valid access token."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
    }
    url = f"{API_BASE_URL}/sale/issues"

    all_issues = []
    offset = 0
    limit = 20

    while True:
        params = {"offset": offset, "limit": limit, "status": "DISPUTE_ONGOING"}
        response = _request_with_retry(
            requests.get,
            url,
            endpoint="discussions",
            headers=headers,
            params=params,
        )
        data = response.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)

        if not issues or len(issues) < limit:
            break
        offset += limit

    return {"issues": all_issues}


def fetch_message_threads(access_token: str) -> dict:
    """Fetch all message threads from Allegro using a valid access token."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    url = f"{API_BASE_URL}/messaging/threads"

    all_threads = []
    offset = 0
    limit = 20

    while True:
        params = {"offset": offset, "limit": limit}
        response = _request_with_retry(
            requests.get,
            url,
            endpoint="message_threads",
            headers=headers,
            params=params,
        )
        data = response.json()
        threads = data.get("threads", [])
        all_threads.extend(threads)

        if not threads or len(threads) < limit:
            break
        offset += limit

    return {"threads": all_threads}


def fetch_discussion_issues(access_token: str, limit: int = 100) -> dict:
    """Fetch all discussion issues (disputes and claims) from Allegro."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
    }
    
    all_issues = []
    offset = 0
    page_limit = min(limit, 100)  # API max is 100
    
    while True:
        params = {"offset": offset, "limit": page_limit}
        url = f"{API_BASE_URL}/sale/issues"
        response = _request_with_retry(
            requests.get, url, endpoint="discussion_issues", headers=headers, params=params
        )
        data = response.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)
        
        if not issues or len(issues) < page_limit or len(all_issues) >= limit:
            break
        offset += page_limit
    
    return {"issues": all_issues[:limit]}


def fetch_discussion_chat(access_token: str, issue_id: str, limit: int = 100) -> dict:
    """
    Pobierz wiadomości z dyskusji lub reklamacji (Issues API).
    
    Endpoint: GET /sale/issues/{issueId}/chat
    
    Args:
        access_token: Token dostępu Allegro
        issue_id: ID dyskusji/reklamacji
        limit: Maksymalna liczba wiadomości (1-100, Issues API akceptuje do 100)
    
    Returns:
        dict: {"chat": [...]} - wiadomości w kolejności od najnowszej do najstarszej
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
    }
    # Issues API akceptuje do 100 wiadomości na stronę
    params = {"limit": min(limit, 100)}
    url = f"{API_BASE_URL}/sale/issues/{issue_id}/chat"
    response = _request_with_retry(
        requests.get, url, endpoint="discussion_chat", headers=headers, params=params
    )
    data = response.json()
    # Debug: log structure
    import logging
    logging.info(f"[DEBUG] fetch_discussion_chat({issue_id}): keys={list(data.keys())}, message_count={len(data.get('chat', []))}")
    return data

def fetch_thread_messages(access_token: str, thread_id: str, limit: int = 20) -> dict:
    """
    Fetch messages for a specific thread.
    
    UWAGA: Messaging API akceptuje maksymalnie limit=20!
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    # API akceptuje max 20 wiadomości na stronę
    params = {"limit": min(limit, 20)}
    url = f"{API_BASE_URL}/messaging/threads/{thread_id}/messages"
    response = _request_with_retry(
        requests.get, url, endpoint="thread_messages", headers=headers, params=params
    )
    data = response.json()
    # Debug: log structure
    import logging
    logging.info(f"[DEBUG] fetch_thread_messages({thread_id}): keys={list(data.keys())}, message_count={len(data.get('messages', []))}")
    return data


def send_thread_message(
    access_token: str, 
    thread_id: str, 
    text: str, 
    attachment_ids: list = None
) -> dict:
    """
    Wyślij wiadomość do wątku w Centrum Wiadomości Allegro.
    
    Args:
        access_token: Token dostępu Allegro
        thread_id: ID wątku
        text: Treść wiadomości (do 2000 znaków)
        attachment_ids: Lista ID załączników (opcjonalne)
    
    Returns:
        dict: Odpowiedź API z danymi wysłanej wiadomości
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
    }
    
    # Przygotuj payload
    payload = {"text": text}
    
    # Dodaj załączniki jeśli są
    if attachment_ids:
        payload["attachments"] = [{"id": aid} for aid in attachment_ids]
    else:
        payload["attachments"] = []
    
    url = f"{API_BASE_URL}/messaging/threads/{thread_id}/messages"
    response = _request_with_retry(
        requests.post, url, endpoint="send_thread_message", headers=headers, json=payload
    )
    return response.json()


def send_discussion_message(
    access_token: str, 
    issue_id: str, 
    text: str,
    attachment_ids: list = None
) -> dict:
    """
    Wyślij wiadomość do dyskusji lub reklamacji (Issues API).
    
    Args:
        access_token: Token dostępu Allegro
        issue_id: ID dyskusji/reklamacji
        text: Treść wiadomości
        attachment_ids: Lista ID załączników (opcjonalne)
    
    Returns:
        dict: Odpowiedź API z danymi wysłanej wiadomości
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
        "Content-Type": "application/vnd.allegro.beta.v1+json",
    }
    
    # Przygotuj payload
    payload = {
        "text": text,
        "type": "REGULAR"  # Zawsze REGULAR dla zwykłych wiadomości
    }
    
    # Dodaj załączniki jeśli są
    if attachment_ids:
        payload["attachments"] = [{"id": aid} for aid in attachment_ids]
    
    url = f"{API_BASE_URL}/sale/issues/{issue_id}/message"
    response = _request_with_retry(
        requests.post,
        url,
        endpoint="send_discussion_message",
        headers=headers,
        json=payload,
    )
    return response.json()


def _describe_token(token: Optional[str]) -> str:
    if not token:
        return "brak"
    if len(token) <= 8:
        return token
    return f"{token[:4]}…{token[-4:]}"


def _extract_allegro_error_details(response) -> dict:
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


def fetch_product_listing(
    ean: str,
    page: int = 1,
    *,
    debug: Optional[Callable[[str, object], None]] = None,
) -> list:
    """Return offers for a product identified by its EAN.

    Parameters
    ----------
    ean : str
        EAN code or search phrase used to look up offers.
    page : int
        Starting page of the listing. Defaults to ``1``.

    Returns
    -------
    list
        A list of dictionaries each containing ``id``, ``seller`` and
        ``sellingMode.price.amount`` for an offer.
    """

    def record(label: str, value: object) -> None:
        if debug is None:
            return
        try:
            debug(label, value)
        except Exception:  # pragma: no cover - defensive
            pass

    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")
    record(
        "Listing Allegro: używany access token",
        _describe_token(token),
    )
    record(
        "Listing Allegro: używany refresh token",
        _describe_token(refresh),
    )
    if not token:
        record(
            "Listing Allegro: błąd przed pobraniem",
            "Missing Allegro access token",
        )
        raise RuntimeError("Missing Allegro access token")

    params = {"page": page}
    if ean.isdigit():
        params["ean"] = ean
    else:
        params["phrase"] = ean

    url = f"{API_BASE_URL}/offers/listing"
    offers = []
    refreshed = False

    def handle_listing_http_error(exc: HTTPError) -> bool:
        nonlocal token, refresh, refreshed
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code not in (401, 403):
            return False

        friendly_message = (
            "Failed to refresh Allegro access token for product listing; "
            "please re-authorize the Allegro integration"
        )

        error_payload = {"status_code": status_code}
        error_payload.update(_extract_allegro_error_details(getattr(exc, "response", None)))
        record("Listing Allegro: otrzymano błąd HTTP", error_payload)

        latest_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        latest_refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")
        if latest_token and latest_token != token:
            token = latest_token
            refresh = latest_refresh
            record(
                "Listing Allegro: znaleziono zaktualizowany access token",
                _describe_token(token),
            )
            return True
        if latest_refresh and latest_refresh != refresh:
            refresh = latest_refresh

        if refresh and not refreshed:
            refreshed = True
            record(
                "Listing Allegro: odświeżanie tokenu",
                _describe_token(refresh),
            )
            try:
                token_data = refresh_token(refresh)
            except Exception as refresh_exc:  # pragma: no cover - defensive
                clear_allegro_tokens()
                _force_clear_allegro_tokens()
                record(
                    "Listing Allegro: odświeżanie nieudane",
                    str(refresh_exc),
                )
                raise RuntimeError(friendly_message) from refresh_exc

            new_token = token_data.get("access_token")
            if not new_token:
                clear_allegro_tokens()
                _force_clear_allegro_tokens()
                record(
                    "Listing Allegro: brak tokenu po odświeżeniu",
                    token_data,
                )
                raise RuntimeError(friendly_message)

            token = new_token
            new_refresh = token_data.get("refresh_token")
            if new_refresh:
                refresh = new_refresh
            expires_in = _safe_int(token_data.get("expires_in")) if token_data else None
            try:
                update_allegro_tokens(token, refresh, expires_in)
            except SettingsPersistenceError as exc:
                friendly_message = (
                    "Cannot refresh Allegro access token because the settings store is "
                    "read-only; please update the credentials manually"
                )
                record(
                    "Listing Allegro: zapis tokenów nieudany",
                    str(exc),
                )
                raise RuntimeError(friendly_message) from exc
            record(
                "Listing Allegro: odświeżanie zakończone",
                {
                    "access_token": _describe_token(token),
                    "refresh_token": _describe_token(refresh),
                },
            )
            return True

        raise RuntimeError(friendly_message) from exc

    while True:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.allegro.public.v1+json",
        }
        try:
            record(
                "Listing Allegro: pobieranie strony",
                {"page": page},
            )
            response = _request_with_retry(
                requests.get,
                url,
                endpoint="listing",
                headers=headers,
                params=params,
            )
        except HTTPError as exc:
            if handle_listing_http_error(exc):
                continue
            raise
        try:
            response.raise_for_status()
        except HTTPError as exc:
            if handle_listing_http_error(exc):
                continue
            raise
        data = response.json()
        record(
            "Listing Allegro: odpowiedź strony",
            {
                "page": page,
                "items": len(data.get("items", {}) or {}),
                "links": list((data.get("links") or {}).keys()),
            },
        )

        items = data.get("items", {})
        page_offers = []
        if isinstance(items, dict):
            for key in ("promoted", "regular", "offers"):
                page_offers.extend(items.get(key, []))
        elif isinstance(items, list):
            page_offers = items

        for offer in page_offers:
            offers.append(
                {
                    "id": offer.get("id"),
                    "seller": offer.get("seller"),
                    "sellingMode": {
                        "price": {
                            "amount": offer.get("sellingMode", {})
                            .get("price", {})
                            .get("amount")
                        }
                    },
                }
            )

        next_link = data.get("links", {}).get("next")
        if not next_link:
            break
        page += 1
        params["page"] = page

    return offers


# ============================================================================
# ZAŁĄCZNIKI W CENTRUM WIADOMOŚCI
# ============================================================================

def download_attachment(access_token: str, attachment_id: str) -> bytes:
    """
    Pobierz załącznik z Centrum Wiadomości Allegro.
    
    Args:
        access_token: Token dostępu Allegro
        attachment_id: ID załącznika (z pola attachment.url w wiadomości)
    
    Returns:
        bytes: Zawartość pliku
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "*/*",
    }
    url = f"{API_BASE_URL}/messaging/message-attachments/{attachment_id}"
    response = _request_with_retry(
        requests.get, url, endpoint="download_attachment", headers=headers
    )
    return response.content


def create_attachment_declaration(
    access_token: str, 
    filename: str, 
    size: int
) -> dict:
    """
    Utwórz deklarację załącznika przed jego przesłaniem.
    
    Args:
        access_token: Token dostępu Allegro
        filename: Nazwa pliku (z rozszerzeniem)
        size: Rozmiar pliku w bajtach
    
    Returns:
        dict: Odpowiedź z ID załącznika {"id": "..."}
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
    }
    payload = {
        "filename": filename,
        "size": size,
    }
    url = f"{API_BASE_URL}/messaging/message-attachments"
    response = _request_with_retry(
        requests.post, 
        url, 
        endpoint="create_attachment_declaration", 
        headers=headers, 
        json=payload
    )
    return response.json()


def upload_attachment(
    access_token: str, 
    attachment_id: str, 
    file_content: bytes,
    content_type: str
) -> dict:
    """
    Prześlij załącznik na serwery Allegro.
    
    Args:
        access_token: Token dostępu Allegro
        attachment_id: ID załącznika (z create_attachment_declaration)
        file_content: Zawartość pliku (binarna)
        content_type: Typ MIME (np. 'image/png', 'application/pdf')
    
    Returns:
        dict: Odpowiedź z ID załącznika {"id": "..."}
    
    Supported content types:
        - image/png
        - image/gif
        - image/bmp
        - image/tiff
        - image/jpeg
        - application/pdf
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": content_type,
    }
    url = f"{API_BASE_URL}/messaging/message-attachments/{attachment_id}"
    response = _request_with_retry(
        requests.put, 
        url, 
        endpoint="upload_attachment", 
        headers=headers, 
        data=file_content
    )
    return response.json()


def upload_attachment_complete(
    access_token: str,
    filename: str,
    file_content: bytes,
    content_type: str
) -> str:
    """
    Pełny proces przesyłania załącznika (deklaracja + upload).
    
    Args:
        access_token: Token dostępu Allegro
        filename: Nazwa pliku
        file_content: Zawartość pliku (binarna)
        content_type: Typ MIME
    
    Returns:
        str: ID załącznika gotowego do użycia w wiadomości
    """
    # 1. Utwórz deklarację
    size = len(file_content)
    declaration = create_attachment_declaration(access_token, filename, size)
    attachment_id = declaration["id"]
    
    # 2. Prześlij plik
    upload_attachment(access_token, attachment_id, file_content, content_type)
    
    return attachment_id


# ============================================================================
# ZAŁĄCZNIKI W DYSKUSJACH I REKLAMACJACH (ISSUES API)
# ============================================================================

def download_issue_attachment(access_token: str, attachment_id: str) -> bytes:
    """
    Pobierz załącznik z dyskusji/reklamacji (Issues API).
    
    Endpoint: GET /sale/issues/attachments/{attachmentId}
    
    Args:
        access_token: Token dostępu Allegro
        attachment_id: ID załącznika
    
    Returns:
        bytes: Zawartość pliku
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    url = f"{API_BASE_URL}/sale/issues/attachments/{attachment_id}"
    response = _request_with_retry(
        requests.get, url, endpoint="download_issue_attachment", headers=headers
    )
    return response.content


def create_issue_attachment_declaration(
    access_token: str, 
    filename: str, 
    size: int
) -> dict:
    """
    Utwórz deklarację załącznika dla dyskusji/reklamacji (Issues API).
    
    Endpoint: POST /sale/issues/attachments
    
    Args:
        access_token: Token dostępu Allegro
        filename: Nazwa pliku (z rozszerzeniem)
        size: Rozmiar pliku w bajtach (max 2097152 = 2MB)
    
    Returns:
        dict: Odpowiedź z ID załącznika {"id": "..."}
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
        "Content-Type": "application/vnd.allegro.beta.v1+json",
    }
    payload = {
        "fileName": filename,
        "size": size,
    }
    url = f"{API_BASE_URL}/sale/issues/attachments"
    response = _request_with_retry(
        requests.post, 
        url, 
        endpoint="create_issue_attachment_declaration", 
        headers=headers, 
        json=payload
    )
    return response.json()


def upload_issue_attachment(
    access_token: str, 
    attachment_id: str, 
    file_content: bytes,
    content_type: str
) -> dict:
    """
    Prześlij załącznik do dyskusji/reklamacji (Issues API).
    
    Endpoint: PUT /sale/issues/attachments/{attachmentId}
    
    Args:
        access_token: Token dostępu Allegro
        attachment_id: ID załącznika (z create_issue_attachment_declaration)
        file_content: Zawartość pliku (binarna)
        content_type: Typ MIME (np. 'image/png', 'application/pdf')
    
    Returns:
        dict: Odpowiedź (pustа)
    
    Supported content types:
        - image/png
        - image/gif
        - image/bmp
        - image/tiff
        - image/jpeg
        - application/pdf
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
        "Content-Type": content_type,
    }
    url = f"{API_BASE_URL}/sale/issues/attachments/{attachment_id}"
    response = _request_with_retry(
        requests.put, 
        url, 
        endpoint="upload_issue_attachment", 
        headers=headers, 
        data=file_content
    )
    # Issues API zwraca pusty response
    return {}


def upload_issue_attachment_complete(
    access_token: str,
    filename: str,
    file_content: bytes,
    content_type: str
) -> str:
    """
    Pełny proces przesyłania załącznika do dyskusji/reklamacji (Issues API).
    
    Args:
        access_token: Token dostępu Allegro
        filename: Nazwa pliku
        file_content: Zawartość pliku (binarna)
        content_type: Typ MIME
    
    Returns:
        str: ID załącznika gotowego do użycia w wiadomości
    """
    # 1. Utwórz deklarację
    size = len(file_content)
    declaration = create_issue_attachment_declaration(access_token, filename, size)
    attachment_id = declaration["id"]
    
    # 2. Prześlij plik
    upload_issue_attachment(access_token, attachment_id, file_content, content_type)
    
    return attachment_id


def fetch_parcel_tracking(access_token: str, carrier_id: str, waybills: list[str]) -> dict:
    """
    Pobierz historię śledzenia przesyłek dla podanych numerów listów przewozowych.
    
    Endpoint: GET /order/carriers/{carrierId}/tracking
    
    Args:
        access_token: Token dostępu Allegro OAuth
        carrier_id: Identyfikator przewoźnika (np. "ALLEGRO", "INPOST", "DPD", "POCZTA_POLSKA")
        waybills: Lista numerów listów przewozowych (max 20)
    
    Returns:
        dict: Historia statusów przesyłek, format:
        {
            "carrierId": "ALLEGRO",
            "waybills": [
                {
                    "waybill": "123456789",
                    "events": [
                        {
                            "occurredAt": "2024-01-15T10:30:00Z",
                            "type": "DELIVERED",
                            "description": "Przesyłka dostarczona"
                        }
                    ]
                }
            ]
        }
    
    Raises:
        ValueError: Jeśli podano więcej niż 20 numerów przesyłek
        HTTPError: Jeśli żądanie API nie powiodło się
    
    Example:
        >>> tracking = fetch_parcel_tracking(token, "INPOST", ["123456789012"])
        >>> for waybill_data in tracking["waybills"]:
        ...     print(f"Waybill: {waybill_data['waybill']}")
        ...     for event in waybill_data["events"]:
        ...         print(f"  {event['occurredAt']}: {event['type']}")
    """
    if len(waybills) > 20:
        raise ValueError("Maksymalnie 20 numerów przesyłek na jedno żądanie")
    
    if not waybills:
        return {"carrierId": carrier_id, "waybills": []}
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    
    # Parametry query: waybill=NUM1&waybill=NUM2&...
    params = [("waybill", wb) for wb in waybills]
    
    url = f"{API_BASE_URL}/order/carriers/{carrier_id}/tracking"
    
    response = _request_with_retry(
        requests.get,
        url,
        endpoint="parcel_tracking",
        headers=headers,
        params=params,
    )
    
    return response.json()


def fetch_billing_entries(
    access_token: str,
    order_id: Optional[str] = None,
    offer_id: Optional[str] = None,
    type_ids: Optional[list[str]] = None,
    occurred_at_gte: Optional[str] = None,
    occurred_at_lte: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """
    Pobierz wpisy billingowe z Allegro API.
    
    Endpoint: GET /billing/billing-entries
    
    Args:
        access_token: Token dostepu Allegro OAuth
        order_id: UUID zamowienia do filtrowania (opcjonalnie)
        offer_id: ID oferty do filtrowania (opcjonalnie)
        type_ids: Lista typow billingowych do filtrowania, np. ["SUC", "LIS"] (opcjonalnie)
        occurred_at_gte: Data od (ISO 8601), np. "2024-01-01T00:00:00Z" (opcjonalnie)
        occurred_at_lte: Data do (ISO 8601) (opcjonalnie)
        limit: Maksymalna liczba wynikow (domyslnie 100)
    
    Returns:
        dict: Slownik z kluczem "billingEntries" zawierajacy liste wpisow billingowych.
        Kazdy wpis zawiera:
        - id: UUID wpisu
        - occurredAt: Data zdarzenia
        - type: {id, name} - typ oplaty (SUC=prowizja, LIS=wystawienie, itp.)
        - offer: {id, name} - powiazana oferta
        - value: {amount, currency} - kwota oplaty
        - balance: {amount, currency} - saldo po operacji
        - order: {id} - UUID zamowienia (jesli dotyczy)
    
    Typy billingowe (najczestsze):
        SUC - Prowizja od sprzedazy (Success Fee)
        LIS - Oplata za wystawienie (Listing Fee)
        SHI - Koszt wysylki
        PRO - Promocja
        REF - Zwrot
    
    Raises:
        HTTPError: Jesli zadanie API nie powiodlo sie
    
    Example:
        >>> entries = fetch_billing_entries(token, order_id="29738e61-7f6a-11e8-ac45-09db60ede9d6")
        >>> for entry in entries.get("billingEntries", []):
        ...     print(f"{entry['type']['name']}: {entry['value']['amount']} PLN")
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    
    params = {"limit": limit}
    
    if order_id:
        params["order.id"] = order_id
    if offer_id:
        params["offer.id"] = offer_id
    if occurred_at_gte:
        params["occurredAt.gte"] = occurred_at_gte
    if occurred_at_lte:
        params["occurredAt.lte"] = occurred_at_lte
    
    # Typy billingowe jako parametry wielokrotne
    if type_ids:
        params_list = [(k, v) for k, v in params.items()]
        for type_id in type_ids:
            params_list.append(("type.id", type_id))
        params = params_list
    
    url = f"{API_BASE_URL}/billing/billing-entries"
    
    response = _request_with_retry(
        requests.get,
        url,
        endpoint="billing_entries",
        headers=headers,
        params=params,
    )
    
    return response.json()


def fetch_billing_types(access_token: str) -> list:
    """
    Pobierz liste wszystkich typow billingowych z Allegro API.
    
    Endpoint: GET /billing/billing-types
    
    Args:
        access_token: Token dostepu Allegro OAuth
    
    Returns:
        list: Lista slownikow z typami billingowymi, kazdy zawiera:
        - id: Kod typu (np. "SUC", "LIS")
        - description: Opis typu w jezyku polskim
    
    Example:
        >>> types = fetch_billing_types(token)
        >>> for t in types:
        ...     print(f"{t['id']}: {t['description']}")
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Accept-Language": "pl-PL",
    }
    
    url = f"{API_BASE_URL}/billing/billing-types"
    
    response = _request_with_retry(
        requests.get,
        url,
        endpoint="billing_types",
        headers=headers,
    )
    
    return response.json()


# =============================================================================
# SZACOWANIE KOSZTOW WYSYLKI ALLEGRO SMART
# =============================================================================
# Tabela kosztow na podstawie:
# https://help.allegro.com/pl/sell/a/allegro-smart-na-allegro-pl-informacje-dla-sprzedajacych-9g0rWRXKxHG
# Aktualizacja: Styczen 2026

from decimal import Decimal

# Progi wartosci zamowienia (w PLN)
ALLEGRO_SMART_THRESHOLDS = [
    (Decimal("30.00"), Decimal("44.99")),
    (Decimal("45.00"), Decimal("64.99")),
    (Decimal("65.00"), Decimal("99.99")),
    (Decimal("100.00"), Decimal("149.99")),
    (Decimal("150.00"), Decimal("999999.99")),
]

# Koszty wysylki dla sprzedajacego wg metody dostawy i progu cenowego
# Format: {klucz_metody: [koszt_prog1, koszt_prog2, koszt_prog3, koszt_prog4, koszt_prog5]}
ALLEGRO_SMART_SHIPPING_COSTS = {
    # === AUTOMATY PACZKOWE I PUNKTY ODBIORU ===
    # Allegro Paczkomaty InPost
    "paczkomaty_inpost": [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")],
    "allegro paczkomaty inpost": [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")],
    "inpost_paczkomaty": [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")],
    
    # Allegro Automat DHL BOX 24/7 (Allegro Delivery)
    "dhl_box": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro automat dhl box": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Automat Pocztex
    "automat_pocztex": [Decimal("1.29"), Decimal("2.49"), Decimal("4.29"), Decimal("6.69"), Decimal("8.89")],
    "allegro automat pocztex": [Decimal("1.29"), Decimal("2.49"), Decimal("4.29"), Decimal("6.69"), Decimal("8.89")],
    
    # Allegro Automat ORLEN Paczka (Allegro Delivery)
    "orlen_automat": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro automat orlen paczka": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "orlen paczka": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Automat DPD Pickup (Allegro Delivery)
    "dpd_automat": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro automat dpd pickup": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro One Box (Allegro Delivery)
    "one_box": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro one box": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Odbiór w Punkcie Pocztex
    "punkt_pocztex": [Decimal("1.29"), Decimal("2.49"), Decimal("4.29"), Decimal("6.69"), Decimal("8.89")],
    "allegro odbior w punkcie pocztex": [Decimal("1.29"), Decimal("2.49"), Decimal("4.29"), Decimal("6.69"), Decimal("8.89")],
    
    # Allegro Odbiór w Punkcie DPD Pickup (bez Allegro Delivery)
    "punkt_dpd": [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")],
    
    # Allegro Odbiór w Punkcie DPD Pickup (Allegro Delivery)
    "punkt_dpd_delivery": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro odbior w punkcie dpd pickup": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Odbiór w Punkcie DHL (Allegro Delivery)
    "punkt_dhl": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro odbior w punkcie dhl": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Odbiór w Punkcie ORLEN Paczka (Allegro Delivery)
    "punkt_orlen": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro odbior w punkcie orlen paczka": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro One Punkt (Allegro Delivery)
    "one_punkt": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro one punkt": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # === PRZESYLKI KURIERSKIE ===
    # Allegro Kurier DPD (bez Allegro Delivery)
    "kurier_dpd": [Decimal("1.99"), Decimal("3.99"), Decimal("5.79"), Decimal("9.09"), Decimal("11.49")],
    "allegro kurier dpd": [Decimal("1.99"), Decimal("3.99"), Decimal("5.79"), Decimal("9.09"), Decimal("11.49")],
    
    # Allegro Kurier DPD (Allegro Delivery)
    "kurier_dpd_delivery": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    
    # Allegro Kurier DHL (Allegro Delivery)
    "kurier_dhl": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    "allegro kurier dhl": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    "dhl": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    
    # Allegro Kurier Pocztex
    "kurier_pocztex": [Decimal("1.99"), Decimal("3.99"), Decimal("5.79"), Decimal("9.09"), Decimal("11.49")],
    "allegro kurier pocztex": [Decimal("1.99"), Decimal("3.99"), Decimal("5.79"), Decimal("9.09"), Decimal("11.49")],
    
    # Allegro One Kurier (Allegro Delivery)
    "one_kurier": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    "allegro one kurier": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    
    # Allegro Przesyłka polecona
    "przesylka_polecona": [Decimal("0.79"), Decimal("1.49"), Decimal("2.29"), Decimal("3.49"), Decimal("4.29")],
    "allegro przesylka polecona": [Decimal("0.79"), Decimal("1.49"), Decimal("2.29"), Decimal("3.49"), Decimal("4.29")],
    
    # Allegro MiniPrzesyłka
    "miniprzesylka": [Decimal("0.79"), Decimal("1.49"), Decimal("2.29"), Decimal("3.49"), Decimal("4.29")],
    "allegro miniprzesylka": [Decimal("0.79"), Decimal("1.49"), Decimal("2.29"), Decimal("3.49"), Decimal("4.29")],
}

# Domyslne koszty (InPost Paczkomaty - najpopularniejsza metoda)
DEFAULT_SHIPPING_COSTS = [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")]


def _normalize_delivery_method(delivery_method: str) -> str:
    """Normalizuj nazwe metody dostawy do klucza slownikowego."""
    if not delivery_method:
        return ""
    # Zamien na male litery i usun nadmiarowe spacje
    normalized = delivery_method.lower().strip()
    # Usun polskie znaki
    normalized = normalized.replace("ó", "o").replace("ł", "l").replace("ą", "a")
    normalized = normalized.replace("ę", "e").replace("ś", "s").replace("ż", "z")
    normalized = normalized.replace("ź", "z").replace("ć", "c").replace("ń", "n")
    return normalized


def _get_threshold_index(order_value: Decimal) -> int:
    """Zwroc indeks progu cenowego dla danej wartosci zamowienia."""
    for i, (min_val, max_val) in enumerate(ALLEGRO_SMART_THRESHOLDS):
        if min_val <= order_value <= max_val:
            return i
    # Powyzej 150 PLN
    if order_value >= Decimal("150.00"):
        return 4
    # Ponizej 30 PLN - brak Smart, uzywamy najnizszego progu
    return 0


def estimate_allegro_shipping_cost(delivery_method: str, order_value: Decimal) -> dict:
    """
    Szacuj koszt wysylki Allegro Smart na podstawie metody dostawy i wartosci zamowienia.
    
    Args:
        delivery_method: Nazwa metody dostawy (np. "Allegro Paczkomaty InPost")
        order_value: Wartosc zamowienia w PLN
    
    Returns:
        dict: {
            "estimated_cost": Decimal - szacowany koszt,
            "threshold_index": int - indeks progu cenowego (0-4),
            "threshold_range": str - zakres cenowy (np. "100.00-149.99 PLN"),
            "delivery_method_matched": str - dopasowana metoda lub "default",
            "is_estimate": True - zawsze True, to szacunek
        }
    """
    normalized = _normalize_delivery_method(delivery_method)
    threshold_idx = _get_threshold_index(order_value)
    
    # Znajdz koszty dla metody dostawy
    costs = None
    matched_method = "default"
    
    # Szukaj dokladnego dopasowania
    if normalized in ALLEGRO_SMART_SHIPPING_COSTS:
        costs = ALLEGRO_SMART_SHIPPING_COSTS[normalized]
        matched_method = normalized
    else:
        # Szukaj czesciowego dopasowania
        for key, cost_list in ALLEGRO_SMART_SHIPPING_COSTS.items():
            if key in normalized or normalized in key:
                costs = cost_list
                matched_method = key
                break
    
    # Jesli nie znaleziono, uzyj domyslnych (InPost)
    if costs is None:
        costs = DEFAULT_SHIPPING_COSTS
        matched_method = "default (inpost)"
    
    estimated_cost = costs[threshold_idx]
    
    # Formatuj zakres progu
    min_val, max_val = ALLEGRO_SMART_THRESHOLDS[threshold_idx]
    if threshold_idx == 4:
        threshold_range = f"od {min_val} PLN"
    else:
        threshold_range = f"{min_val}-{max_val} PLN"
    
    return {
        "estimated_cost": estimated_cost,
        "threshold_index": threshold_idx,
        "threshold_range": threshold_range,
        "delivery_method_matched": matched_method,
        "is_estimate": True,
    }


def get_order_billing_summary(
    access_token: str, 
    order_id: str,
    delivery_method: str = None,
    order_value: Decimal = None
) -> dict:
    """
    Pobierz podsumowanie kosztow billingowych dla zamowienia.
    
    Agreguje wszystkie wpisy billingowe dla danego zamowienia i zwraca
    podsumowanie z podzilem na typy oplat. Jesli API nie zwroci kosztu wysylki,
    a podano delivery_method i order_value, szacuje koszt na podstawie tabeli Allegro Smart.
    
    Args:
        access_token: Token dostepu Allegro OAuth
        order_id: UUID zamowienia (format: "29738e61-7f6a-11e8-ac45-09db60ede9d6")
        delivery_method: Opcjonalna nazwa metody dostawy do szacowania
        order_value: Opcjonalna wartosc zamowienia do szacowania
    
    Returns:
        dict: Slownik z podsumowaniem kosztow:
        {
            "success": True/False,
            "commission": Decimal - prowizja od sprzedazy,
            "listing_fee": Decimal - oplata za wystawienie,
            "shipping_fee": Decimal - koszty wysylki,
            "promo_fee": Decimal - oplaty promocyjne,
            "other_fees": Decimal - pozostale oplaty,
            "total_fees": Decimal - suma wszystkich oplat,
            "refunds": Decimal - zwroty (wartosci dodatnie),
            "entries": list - surowe wpisy billingowe,
            "fee_details": list - szczegoly oplat z nazwami,
            "error": str - komunikat bledu (jesli success=False)
        }
    
    Example:
        >>> summary = get_order_billing_summary(token, "29738e61-7f6a-11e8-ac45-09db60ede9d6")
        >>> if summary["success"]:
        ...     print(f"Prowizja: {summary['commission']} PLN")
        ...     print(f"Suma oplat: {summary['total_fees']} PLN")
    """
    from decimal import Decimal
    
    result = {
        "success": False,
        "commission": Decimal("0"),      # Prowizje od sprzedazy
        "listing_fee": Decimal("0"),     # Oplata za wystawienie
        "shipping_fee": Decimal("0"),    # Koszty wysylki
        "promo_fee": Decimal("0"),       # Promocje i reklamy
        "other_fees": Decimal("0"),      # Pozostale
        "total_fees": Decimal("0"),
        "refunds": Decimal("0"),         # Zwroty (dodatnie)
        "entries": [],
        "fee_details": [],               # Szczegoly oplat z nazwami
        "error": None,
    }
    
    # Mapowanie typow billingowych Allegro na kategorie
    # Zrodlo: rzeczywiste dane z API Allegro Billing
    COMMISSION_TYPES = {
        "SUC",   # Prowizja od sprzedazy
        "FSF",   # Prowizja od sprzedazy oferty wyroznonej
        "BRG",   # Prowizja od sprzedazy w Kampanii
    }
    
    SHIPPING_TYPES = {
        "HLB",   # Oplata za dostawe DHL Allegro Delivery
        "ORB",   # Oplata za dostawe ORLEN Paczka Allegro Delivery
        "DXP",   # Oplata za dostawe One Kurier Allegro Delivery
        "HB4",   # Oplata za dostawe InPost
        "SHI",   # Oplata za wysylke (ogolna)
        "SHIP",  # Wysylka
        "DLV",   # Dostawa
    }
    
    PROMO_TYPES = {
        "FEA",   # Oplata za wyroznenie
        "DPG",   # Oplata za promowanie na stronie dzialu
        "PRO",   # Promocja
        "ADS",   # Reklama
    }
    
    REFUND_TYPES = {
        "REF",   # Zwrot kosztow
        "CB2",   # Bonus z Kampanii
        "PAD",   # Pobranie oplat z wplywow (dodatnie)
    }
    
    LISTING_TYPES = {
        "LIS",   # Oplata za wystawienie
    }
    
    try:
        data = fetch_billing_entries(access_token, order_id=order_id)
        entries = data.get("billingEntries", [])
        result["entries"] = entries
        
        for entry in entries:
            type_info = entry.get("type", {})
            type_id = type_info.get("id", "")
            type_name = type_info.get("name", type_id)
            value = entry.get("value", {})
            amount_str = value.get("amount", "0")
            
            try:
                amount = Decimal(amount_str)
            except Exception:
                amount = Decimal("0")
            
            # Dodaj do szczegolowych oplat (tylko koszty, nie zwroty)
            if amount < 0:
                result["fee_details"].append({
                    "type_id": type_id,
                    "name": type_name,
                    "amount": abs(amount),
                })
            
            # Klasyfikuj wg typu
            if type_id in COMMISSION_TYPES:
                result["commission"] += abs(amount) if amount < 0 else Decimal("0")
            elif type_id in LISTING_TYPES:
                result["listing_fee"] += abs(amount) if amount < 0 else Decimal("0")
            elif type_id in SHIPPING_TYPES:
                # Koszty wysylki - ujemne to koszty, dodatnie to zwroty
                if amount < 0:
                    result["shipping_fee"] += abs(amount)
                else:
                    result["refunds"] += amount
            elif type_id in PROMO_TYPES:
                result["promo_fee"] += abs(amount) if amount < 0 else Decimal("0")
            elif type_id in REFUND_TYPES:
                # Zwroty i bonusy (dodatnie to wplywy)
                if amount > 0:
                    result["refunds"] += amount
            else:
                # Pozostale oplaty
                if amount < 0:
                    result["other_fees"] += abs(amount)
                    result["fee_details"].append({
                        "type_id": type_id,
                        "name": type_name,
                        "amount": abs(amount),
                    })
        
        # Suma wszystkich oplat (bez zwrotow)
        result["total_fees"] = (
            result["commission"] +
            result["listing_fee"] +
            result["shipping_fee"] +
            result["promo_fee"] +
            result["other_fees"]
        )
        
        result["success"] = True
        
    except Exception as e:
        result["error"] = str(e)
    
    # Jesli API nie zwrocilo kosztu wysylki, a mamy dane do szacowania - oszacuj
    if result["shipping_fee"] == Decimal("0") and delivery_method and order_value:
        estimate = estimate_allegro_shipping_cost(delivery_method, order_value)
        result["estimated_shipping"] = estimate
        result["shipping_fee_estimated"] = estimate["estimated_cost"]
        # Dodaj szacowany koszt do fee_details
        result["fee_details"].append({
            "type_id": "EST",
            "name": f"Szacowany koszt wysylki ({estimate['delivery_method_matched']})",
            "amount": estimate["estimated_cost"],
            "is_estimate": True,
        })
        # Zaktualizuj sume oplat z szacowanym kosztem
        result["total_fees_with_estimate"] = result["total_fees"] + estimate["estimated_cost"]
    else:
        result["estimated_shipping"] = None
        result["shipping_fee_estimated"] = None
        result["total_fees_with_estimate"] = result["total_fees"]
    
    return result
