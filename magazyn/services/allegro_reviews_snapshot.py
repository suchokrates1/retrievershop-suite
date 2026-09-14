"""Snapshot listy opinii Allegro (z komentarzem) na homepage sklepu."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from ..allegro_api.core import ALLEGRO_USER_AGENT
from ..settings_store import settings_store

logger = logging.getLogger(__name__)

SETTING_KEY = "ALLEGRO_REVIEWS_SNAPSHOT"
SYNC_MAX_AGE_SECONDS = 6 * 3600
DEFAULT_LIMIT = 12
MAX_FETCH_PAGES = 12
PAGE_SIZE = 100


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }


def _mask_login(login: str) -> str:
    login = (login or "").strip()
    if not login:
        return "Klient Allegro"
    if login.lower().startswith("client:"):
        return "Klient Allegro"
    if len(login) <= 2:
        return login[0] + "*"
    # Keep first char + rest partially visible for recognizability (public on Allegro)
    return login


def _stars_from_rates(rates: dict[str, Any] | None) -> float:
    if not isinstance(rates, dict) or not rates:
        return 5.0
    vals = [float(v) for v in rates.values() if isinstance(v, (int, float))]
    if not vals:
        return 5.0
    return round(sum(vals) / len(vals), 1)


def _normalize_comment(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text[:420]


def fetch_reviews_with_comments(
    access_token: str | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Pobierz polecane oceny z niepustym komentarzem (najnowsze pierwsze)."""
    token = access_token or settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("missing ALLEGRO_ACCESS_TOKEN")

    headers = _headers(token)
    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    offset = 0

    for _ in range(MAX_FETCH_PAGES):
        resp = requests.get(
            "https://api.allegro.pl/sale/user-ratings",
            headers=headers,
            params={"recommended": "true", "limit": PAGE_SIZE, "offset": offset},
            timeout=30,
        )
        resp.raise_for_status()
        ratings = resp.json().get("ratings") or []
        if not ratings:
            break

        for item in ratings:
            comment = _normalize_comment(str(item.get("comment") or ""))
            if len(comment) < 8:
                continue
            login = str((item.get("buyer") or {}).get("login") or "")
            dedupe = f"{login.lower()}|{comment.lower()[:80]}"
            if dedupe in seen_keys:
                continue
            seen_keys.add(dedupe)

            offers = ((item.get("order") or {}).get("offers") or [])
            offer_title = ""
            if offers and isinstance(offers[0], dict):
                offer_title = str(offers[0].get("title") or "")

            out.append(
                {
                    "id": str(item.get("id") or ""),
                    "login": _mask_login(login),
                    "comment": comment,
                    "created_at": str(item.get("createdAt") or item.get("lastChangedAt") or ""),
                    "recommended": bool(item.get("recommended")),
                    "stars": _stars_from_rates(item.get("rates") if isinstance(item.get("rates"), dict) else None),
                    "offer_title": offer_title[:120],
                }
            )
            if len(out) >= limit:
                return out

        offset += len(ratings)
        if len(ratings) < PAGE_SIZE:
            break

    return out


def sync_reviews_snapshot(*, force: bool = False, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    existing = load_reviews_snapshot()
    if not force and existing:
        age = _age_seconds(existing)
        if age is not None and age < SYNC_MAX_AGE_SECONDS and len(existing.get("reviews") or []) >= 3:
            return existing

    reviews = fetch_reviews_with_comments(limit=limit)
    login = "Retriever_Shop"
    try:
        from .allegro_ratings_snapshot import load_snapshot

        snap = load_snapshot() or {}
        login = str(snap.get("login") or login)
    except Exception:
        pass

    snapshot = {
        "login": login,
        "profile_url": f"https://allegro.pl/uzytkownik/{login}",
        "reviews": reviews,
        "count": len(reviews),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source": "allegro_api",
    }
    settings_store.update({SETTING_KEY: json.dumps(snapshot, ensure_ascii=False)})
    logger.info("Allegro reviews snapshot: %s opinions", len(reviews))
    return snapshot


def load_reviews_snapshot() -> dict[str, Any] | None:
    raw = settings_store.get(SETTING_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _age_seconds(snapshot: dict[str, Any]) -> float | None:
    synced = snapshot.get("synced_at")
    if not synced:
        return None
    try:
        dt = datetime.fromisoformat(str(synced).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def get_public_reviews(*, limit: int = DEFAULT_LIMIT, refresh_if_stale: bool = True) -> dict[str, Any] | None:
    try:
        if refresh_if_stale:
            snap = sync_reviews_snapshot(force=False, limit=max(limit, DEFAULT_LIMIT))
        else:
            snap = load_reviews_snapshot()
    except Exception as exc:
        logger.warning("Allegro reviews sync failed, serving cache: %s", exc)
        snap = load_reviews_snapshot()
    if not snap:
        return None
    reviews = list(snap.get("reviews") or [])[: max(1, min(24, limit))]
    return {
        "login": snap.get("login"),
        "profile_url": snap.get("profile_url"),
        "reviews": reviews,
        "count": len(reviews),
        "synced_at": snap.get("synced_at"),
    }


__all__ = [
    "SETTING_KEY",
    "fetch_reviews_with_comments",
    "sync_reviews_snapshot",
    "load_reviews_snapshot",
    "get_public_reviews",
]
