import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests
from requests import Response
from requests.exceptions import HTTPError, RequestException

from .env_tokens import clear_allegro_tokens, update_allegro_tokens
from .metrics import (
    ALLEGRO_API_ERRORS_TOTAL,
    ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS,
    ALLEGRO_API_RETRIES_TOTAL,
)

AUTH_URL = "https://allegro.pl/auth/oauth/token"
API_BASE_URL = "https://api.allegro.pl"
DEFAULT_TIMEOUT = 10
MAX_RETRY_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 30


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
    delay = _rate_limit_delay(response.headers)
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
    """Refresh the access token using a refresh token.

    The client identifier and secret can be provided via the environment
    variables ``ALLEGRO_CLIENT_ID`` and ``ALLEGRO_CLIENT_SECRET``.
    """
    client_id = os.getenv("ALLEGRO_CLIENT_ID")
    client_secret = os.getenv("ALLEGRO_CLIENT_SECRET")
    auth = (client_id, client_secret) if client_id and client_secret else None

    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    response = requests.post(AUTH_URL, data=data, auth=auth, timeout=DEFAULT_TIMEOUT)
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


def fetch_product_listing(ean: str, page: int = 1) -> list:
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

    token = os.getenv("ALLEGRO_ACCESS_TOKEN")
    refresh = os.getenv("ALLEGRO_REFRESH_TOKEN")
    if not token:
        raise RuntimeError("Missing Allegro access token")

    params = {"page": page}
    if ean.isdigit():
        params["ean"] = ean
    else:
        params["phrase"] = ean

    url = f"{API_BASE_URL}/offers/listing"
    offers = []
    refreshed = False

    while True:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.allegro.public.v1+json",
        }
        response = _request_with_retry(
            requests.get,
            url,
            endpoint="listing",
            headers=headers,
            params=params,
        )
        try:
            response.raise_for_status()
        except HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (401, 403):
                friendly_message = (
                    "Failed to refresh Allegro access token for product listing; "
                    "please re-authorize the Allegro integration"
                )
                if refresh and not refreshed:
                    refreshed = True
                    try:
                        token_data = refresh_token(refresh)
                    except Exception as refresh_exc:
                        clear_allegro_tokens()
                        raise RuntimeError(friendly_message) from refresh_exc
                    new_token = token_data.get("access_token")
                    if not new_token:
                        clear_allegro_tokens()
                        raise RuntimeError(friendly_message)
                    token = new_token
                    new_refresh = token_data.get("refresh_token")
                    if new_refresh:
                        refresh = new_refresh
                    update_allegro_tokens(token, refresh)
                    continue
                raise RuntimeError(friendly_message) from exc
            raise
        data = response.json()

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
