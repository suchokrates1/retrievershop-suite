"""Okresowa synchronizacja slownika billing types z Allegro."""

from __future__ import annotations

import logging
import threading

from .settings_store import settings_store
from .services.billing_types import sync_billing_types_dictionary
from .services.runtime import BackgroundThreadRuntime

logger = logging.getLogger(__name__)

_sync_thread: threading.Thread | None = None
_runtime = BackgroundThreadRuntime(name="BillingTypesScheduler", logger=logger)
_stop_event = _runtime.stop_event

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

    _runtime.start(
        _billing_types_worker,
        app,
        already_running_message="Billing types scheduler already running",
        started_message="Billing types scheduler thread started",
    )
    _sync_thread = _runtime.thread


def stop_billing_types_scheduler():
    global _sync_thread

    _runtime.stop(
        stopping_message="Stopping billing types scheduler...",
        stopped_message="Billing types scheduler stopped",
    )
    _sync_thread = None
