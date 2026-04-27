"""Synchronizacja zamowien z Allegro przez Events API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from dateutil import parser as dateparser
from sqlalchemy.exc import IntegrityError

from ..allegro_api.events import fetch_event_stats, fetch_order_events
from ..allegro_api.orders import (
    fetch_allegro_order_detail,
    get_allegro_internal_status,
    parse_allegro_order_to_data,
)
from ..db import get_session
from ..models.orders import OrderEvent
from ..settings_store import settings_store
from .order_status import add_order_status
from .order_sync import sync_order_from_data

logger = logging.getLogger(__name__)

IMPORT_EVENT_TYPES = {"BOUGHT", "FILLED_IN", "READY_FOR_PROCESSING"}
CANCEL_EVENT_TYPES = {"BUYER_CANCELLED", "AUTO_CANCELLED"}


def sync_from_allegro_events(app, *, log: logging.Logger | None = None) -> dict[str, int]:
    """Synchronizuj zamowienia z Allegro przez Events API inkrementalnie."""
    active_logger = log or logger
    stats = {
        "events_fetched": 0,
        "events_stored": 0,
        "orders_synced": 0,
        "orders_cancelled": 0,
        "orders_skipped": 0,
        "errors": 0,
    }

    try:
        last_event_id, initialized = _get_or_initialize_cursor(stats, active_logger)
        if not last_event_id or initialized:
            return stats

        all_events = _fetch_events_since(last_event_id, stats, active_logger)
        stats["events_fetched"] = len(all_events)

        if not all_events:
            active_logger.debug("Allegro Events: brak nowych zdarzen")
            return stats

        active_logger.info("Allegro Events: pobrano %s nowych zdarzen", len(all_events))

        with app.app_context():
            _process_events(all_events, stats, active_logger)

        new_last_id = all_events[-1].get("id")
        if new_last_id:
            settings_store.update({"ALLEGRO_LAST_EVENT_ID": new_last_id})
            active_logger.info("Allegro Events: kursor zaktualizowany na %s", new_last_id)

    except Exception as exc:
        active_logger.error("Allegro Events: krytyczny blad: %s", exc, exc_info=True)
        stats["errors"] += 1

    return stats


def _get_or_initialize_cursor(stats: dict[str, int], log: logging.Logger) -> tuple[str | None, bool]:
    last_event_id = settings_store.get("ALLEGRO_LAST_EVENT_ID")
    if last_event_id:
        return last_event_id, False

    log.info("Allegro Events: brak kursora, inicjalizacja na najnowszym zdarzeniu")
    try:
        event_stats = fetch_event_stats()
        latest = event_stats.get("latestEvent", {})
        last_event_id = latest.get("id")
        if last_event_id:
            settings_store.update({"ALLEGRO_LAST_EVENT_ID": last_event_id})
            log.info("Allegro Events: kursor zainicjalizowany na %s", last_event_id)
        else:
            log.warning("Allegro Events: brak zdarzen do inicjalizacji")
        return last_event_id, True
    except Exception as exc:
        log.error("Allegro Events: blad inicjalizacji kursora: %s", exc)
        stats["errors"] += 1
        return None, True


def _fetch_events_since(
    last_event_id: str,
    stats: dict[str, int],
    log: logging.Logger,
    *,
    max_pages: int = 10,
) -> list[dict]:
    all_events = []
    current_from = last_event_id

    for _ in range(max_pages):
        try:
            result = fetch_order_events(from_event_id=current_from, limit=1000)
        except Exception as exc:
            log.error("Allegro Events: blad pobierania zdarzen: %s", exc)
            stats["errors"] += 1
            break

        events = result.get("events", [])
        if not events:
            break

        all_events.extend(events)
        current_from = events[-1].get("id")

        if len(events) < 1000:
            break

    return all_events


def _process_events(all_events: list[dict], stats: dict[str, int], log: logging.Logger) -> None:
    with get_session() as db:
        seen_import_checkout_forms = set()

        for event in all_events:
            event_id = event.get("id", "")
            event_type = event.get("type", "")
            order_info = event.get("order", {})
            checkout_form_id = order_info.get("checkoutForm", {}).get("id")
            occurred_at = _parse_event_timestamp(event.get("occurredAt", ""))

            if not checkout_form_id:
                continue

            order_id = f"allegro_{checkout_form_id}"

            if event_type in IMPORT_EVENT_TYPES and checkout_form_id in seen_import_checkout_forms:
                stats["orders_skipped"] += 1
                _store_raw_event(db, order_id, event_id, event_type, occurred_at, event, stats, log)
                continue

            if event_type in IMPORT_EVENT_TYPES:
                seen_import_checkout_forms.add(checkout_form_id)
                if not _sync_import_event(db, checkout_form_id, event_type, stats, log):
                    continue
            elif event_type in CANCEL_EVENT_TYPES:
                if not _sync_cancel_event(db, order_id, checkout_form_id, event_type, stats, log):
                    continue
            else:
                stats["orders_skipped"] += 1
                continue

            _store_raw_event(db, order_id, event_id, event_type, occurred_at, event, stats, log)

        db.commit()


def _sync_import_event(db, checkout_form_id: str, event_type: str, stats: dict[str, int], log) -> bool:
    try:
        detail = fetch_allegro_order_detail(checkout_form_id)
        order_data = parse_allegro_order_to_data(detail)
        sync_order_from_data(db, order_data)
        internal_status = get_allegro_internal_status(order_data)
        add_order_status(
            db,
            order_data["order_id"],
            internal_status,
            notes=f"Allegro event: {event_type}",
        )
        stats["orders_synced"] += 1
        log.info("Allegro Events: zsynchronizowano zamowienie %s", checkout_form_id)
        return True
    except Exception as exc:
        log.error("Allegro Events: blad syncu zamowienia %s: %s", checkout_form_id, exc)
        stats["errors"] += 1
        return False


def _sync_cancel_event(
    db,
    order_id: str,
    checkout_form_id: str,
    event_type: str,
    stats: dict[str, int],
    log,
) -> bool:
    try:
        add_order_status(
            db,
            order_id,
            "anulowano",
            notes=f"Allegro event: {event_type}",
        )
        stats["orders_cancelled"] += 1
        log.info("Allegro Events: anulowano zamowienie %s (%s)", checkout_form_id, event_type)
        return True
    except Exception as exc:
        log.warning("Allegro Events: blad anulowania %s: %s", checkout_form_id, exc)
        stats["errors"] += 1
        return False


def _store_raw_event(
    db,
    order_id: str,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    event: dict,
    stats: dict[str, int],
    log: logging.Logger,
) -> None:
    try:
        nested = db.begin_nested()
        event_record = OrderEvent(
            order_id=order_id,
            allegro_event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            payload_json=str(event),
        )
        db.add(event_record)
        db.flush()
        stats["events_stored"] += 1
        log.debug("Allegro Events: zapisano raw event %s", event_id)
    except IntegrityError:
        nested.rollback()
        log.debug("Allegro Events: event %s juz istnieje, pominieto", event_id)
    except Exception as exc:
        nested.rollback()
        log.warning("Allegro Events: blad zapisu raw event %s: %s", event_id, exc)


def _parse_event_timestamp(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return dateparser.isoparse(value)
    except Exception:
        return datetime.now(timezone.utc)


__all__ = ["sync_from_allegro_events"]