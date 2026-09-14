"""Snapshot ocen sprzedawcy Allegro (trust badge na sklepie)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import requests

from ..allegro_api.core import ALLEGRO_USER_AGENT
from ..settings_store import settings_store

logger = logging.getLogger(__name__)

SETTING_KEY = "ALLEGRO_RATINGS_SNAPSHOT"
DEFAULT_LOGIN = "Retriever_Shop"
SYNC_MAX_AGE_SECONDS = 6 * 3600


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }


def fetch_ratings_snapshot(access_token: str | None = None) -> dict[str, Any]:
    """Pobierz podsumowanie ocen z Allegro API."""
    token = access_token or settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("missing ALLEGRO_ACCESS_TOKEN")

    headers = _headers(token)
    me = requests.get("https://api.allegro.pl/me", headers=headers, timeout=25)
    me.raise_for_status()
    me_data = me.json()
    user_id = str(me_data.get("id") or "")
    login = str(me_data.get("login") or DEFAULT_LOGIN)
    if not user_id:
        raise RuntimeError("allegro /me missing id")

    summary = requests.get(
        f"https://api.allegro.pl/users/{user_id}/ratings-summary",
        headers=headers,
        timeout=25,
    )
    summary.raise_for_status()
    data = summary.json()

    recommended = data.get("recommended") or {}
    not_recommended = data.get("notRecommended") or {}
    stats = data.get("statistics") or {}
    received = (stats.get("received") or {}).get("total")
    user_meta = data.get("user") or {}

    orders_total = _count_orders()
    orders_rounded = (orders_total // 100) * 100

    snapshot = {
        "user_id": user_id,
        "login": login,
        "profile_url": f"https://allegro.pl/uzytkownik/{login}",
        "recommended_percentage": str(data.get("recommendedPercentage") or ""),
        "recommended_unique": int(recommended.get("unique") or 0),
        "recommended_total": int(recommended.get("total") or 0),
        "not_recommended_unique": int(not_recommended.get("unique") or 0),
        "not_recommended_total": int(not_recommended.get("total") or 0),
        "ratings_received_total": int(received or 0),
        "seller_since": str(user_meta.get("createdAt") or "")[:10],
        "orders_total": orders_total,
        "orders_rounded_100": orders_rounded,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source": "allegro_api",
    }
    return snapshot


def _count_orders() -> int:
    """Liczba zamówień w magazynie (Allegro + Woo + manual)."""
    try:
        from sqlalchemy import text

        from ..db import configure_engine, get_session

        configure_engine()
        with get_session() as db:
            total = db.execute(text("SELECT COUNT(*) FROM orders")).scalar()
            return int(total or 0)
    except Exception as exc:
        logger.warning("orders count for trust snapshot failed: %s", exc)
        return 0


def save_snapshot(snapshot: dict[str, Any]) -> None:
    settings_store.update({SETTING_KEY: json.dumps(snapshot, ensure_ascii=False)})


def load_snapshot() -> dict[str, Any] | None:
    raw = settings_store.get(SETTING_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def snapshot_age_seconds(snapshot: dict[str, Any] | None = None) -> float | None:
    snap = snapshot if snapshot is not None else load_snapshot()
    if not snap:
        return None
    synced = snap.get("synced_at")
    if not synced:
        return None
    try:
        dt = datetime.fromisoformat(str(synced).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def sync_ratings_snapshot(*, force: bool = False) -> dict[str, Any]:
    """Odśwież snapshot gdy jest stary albo force=True."""
    existing = load_snapshot()
    age = snapshot_age_seconds(existing)
    if not force and existing and age is not None and age < SYNC_MAX_AGE_SECONDS:
        return existing

    snapshot = fetch_ratings_snapshot()
    save_snapshot(snapshot)
    logger.info(
        "Allegro ratings snapshot: %s%% / %s ocen (login=%s)",
        snapshot.get("recommended_percentage"),
        snapshot.get("ratings_received_total"),
        snapshot.get("login"),
    )
    return snapshot


def get_public_snapshot(*, refresh_if_stale: bool = True) -> dict[str, Any] | None:
    if refresh_if_stale:
        try:
            return sync_ratings_snapshot(force=False)
        except Exception as exc:
            logger.warning("Allegro ratings sync failed, serving cache: %s", exc)
    return load_snapshot()


__all__ = [
    "SETTING_KEY",
    "fetch_ratings_snapshot",
    "save_snapshot",
    "load_snapshot",
    "sync_ratings_snapshot",
    "get_public_snapshot",
]
