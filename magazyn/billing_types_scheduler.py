"""Okresowa synchronizacja slownika billing types z Allegro."""

from __future__ import annotations

import logging
import threading

from .settings_store import settings_store
from .stats import sync_billing_types_dictionary

logger = logging.getLogger(__name__)

_sync_thread: threading.Thread | None = None
_stop_event = threading.Event()

SYNC_INTERVAL_SECONDS = 6 * 3600


def _billing_types_worker(app):
    logger.info("Billing types scheduler started - interval %ss", SYNC_INTERVAL_SECONDS)
    while not _stop_event.is_set():
        try:
            with app.app_context():
                token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
                if not token:
                    logger.info("Billing types scheduler: brak tokenu Allegro, pomijam przebieg")
                else:
                    result = sync_billing_types_dictionary(token)
                    logger.info(
                        "Billing types sync done: fetched=%s, known=%s, created=%s",
                        result.get("fetched", 0),
                        result.get("known", 0),
                        result.get("created", 0),
                    )
        except Exception as exc:
            logger.error("Billing types scheduler error: %s", exc, exc_info=True)

        _stop_event.wait(SYNC_INTERVAL_SECONDS)

    logger.info("Billing types scheduler stopped")


def start_billing_types_scheduler(app):
    global _sync_thread

    if _sync_thread is not None and _sync_thread.is_alive():
        logger.warning("Billing types scheduler already running")
        return

    _stop_event.clear()
    _sync_thread = threading.Thread(
        target=_billing_types_worker,
        args=(app,),
        daemon=True,
        name="BillingTypesScheduler",
    )
    _sync_thread.start()
    logger.info("Billing types scheduler thread started")


def stop_billing_types_scheduler():
    global _sync_thread

    if _sync_thread is None or not _sync_thread.is_alive():
        return

    logger.info("Stopping billing types scheduler...")
    _stop_event.set()
    _sync_thread.join(timeout=5)
    _sync_thread = None
    logger.info("Billing types scheduler stopped")
