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


def fetch_offers(access_token: str, offset: int = 0, limit: int = 100) -> dict:
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

    Returns
    -------
    dict
        JSON response with the list of offers.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    params = {"offset": offset, "limit": limit}
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
