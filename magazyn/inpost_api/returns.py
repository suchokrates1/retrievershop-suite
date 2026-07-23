"""InPost Returns REST API (OAuth) — kody zwrotów paczkomatowych.

Wymaga osobnych credentials (INPOST_RETURNS_CLIENT_ID/SECRET),
nie mylić z ShipX INPOST_TOKEN.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from ..settings_store import settings_store

logger = logging.getLogger(__name__)

LOGIN_URL = (
    "https://login.inpost.pl/auth/realms/external/protocol/openid-connect/token"
)
API_BASE = "https://api.inpost.pl"


class InpostReturnsError(Exception):
    """Błąd Returns API."""

    def __init__(self, message: str, *, status: int | None = None, details: Any = None):
        super().__init__(message)
        self.status = status
        self.details = details


def returns_credentials_configured() -> bool:
    client_id = (settings_store.get("INPOST_RETURNS_CLIENT_ID") or "").strip()
    client_secret = (settings_store.get("INPOST_RETURNS_CLIENT_SECRET") or "").strip()
    return bool(client_id and client_secret)


def _to_e164_pl(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if digits.startswith("48") and len(digits) >= 11:
        digits = digits[2:]
    if len(digits) == 9:
        return f"+48{digits}"
    if (phone or "").startswith("+") and len(digits) >= 10:
        return f"+{digits}"
    raise InpostReturnsError("Nieprawidłowy numer telefonu (wymagane 9 cyfr PL)")


def get_access_token() -> str:
    client_id = (settings_store.get("INPOST_RETURNS_CLIENT_ID") or "").strip()
    client_secret = (settings_store.get("INPOST_RETURNS_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise InpostReturnsError("Brak INPOST_RETURNS_CLIENT_ID / INPOST_RETURNS_CLIENT_SECRET")
    response = requests.post(
        LOGIN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise InpostReturnsError(
            f"OAuth failed HTTP {response.status_code}",
            status=response.status_code,
            details=response.text[:500],
        )
    data = response.json() or {}
    token = data.get("access_token")
    if not token:
        raise InpostReturnsError("OAuth response without access_token", details=data)
    return str(token)


def create_return_ticket(
    *,
    sender_first_name: str,
    sender_last_name: str,
    sender_phone: str,
    sender_email: str,
    external_reference: str,
    size: str = "A",
    expiration_days: int = 14,
    description: str = "",
) -> Dict[str, Any]:
    """POST /v1/returns/tickets — oczekujemy pola code (paperless)."""
    token = get_access_token()
    phone = _to_e164_pl(sender_phone)
    size = (size or "A").upper()
    if size not in {"A", "B", "C"}:
        size = "A"
    # Docs: min now+7 days, max now+720
    days = max(7, min(int(expiration_days or 14), 720))
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    payload: Dict[str, Any] = {
        "shipment": {
            "size": size,
            "sender": {
                "firstName": (sender_first_name or "Klient")[:125],
                "lastName": (sender_last_name or "Zwrot")[:125],
                "phone": phone,
                "email": (sender_email or "")[:255],
            },
        },
        "expirationDate": expires.isoformat().replace("+00:00", "Z"),
        "externalReference": (external_reference or "")[:64],
    }
    if description:
        payload["description"] = description[:255]

    response = requests.post(
        f"{API_BASE}/v1/returns/tickets",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if response.status_code >= 400:
        raise InpostReturnsError(
            f"Create return ticket HTTP {response.status_code}",
            status=response.status_code,
            details=response.text[:800],
        )
    data = response.json() or {}
    if not data.get("code") and not data.get("labelUrl"):
        logger.warning("Returns ticket without code/labelUrl: %s", data)
    return data


__all__ = [
    "InpostReturnsError",
    "create_return_ticket",
    "get_access_token",
    "returns_credentials_configured",
]
