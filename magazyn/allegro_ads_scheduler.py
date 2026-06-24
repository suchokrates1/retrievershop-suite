"""Codzienny scheduler synchronizacji Allegro Ads Panel (8:00 Europe/Warsaw)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .services.allegro_ads_panel.sync import sync_ads_panel_statistics
from .services.runtime import BackgroundThreadRuntime

logger = logging.getLogger(__name__)

WARSAW = ZoneInfo("Europe/Warsaw")
SYNC_HOUR = 8

_scheduler_thread: Optional[threading.Thread] = None
_runtime = BackgroundThreadRuntime(name="AllegroAdsScheduler", logger=logger)
_stop_event = _runtime.stop_event
_last_run_date: Optional[str] = None


def _scheduler_worker(app) -> None:
    global _last_run_date
    logger.info("Allegro Ads scheduler started - daily at %s:00 (%s)", SYNC_HOUR, WARSAW)
    while not _stop_event.is_set():
        now = datetime.now(WARSAW)
        today = now.date().isoformat()
        if now.hour == SYNC_HOUR and _last_run_date != today:
            try:
                with app.app_context():
                    result = sync_ads_panel_statistics(snapshot_date=now.date())
                    logger.info(
                        "Allegro Ads sync OK: campaigns=%s sold=%s chart=%s",
                        result.get("campaigns_synced"),
                        result.get("sold_items_synced"),
                        result.get("chart_points"),
                    )
                _last_run_date = today
            except Exception as exc:
                logger.error("Allegro Ads sync failed: %s", exc, exc_info=True)
            _stop_event.wait(3600)
        else:
            _stop_event.wait(60)
    logger.info("Allegro Ads scheduler stopped")


def start_allegro_ads_scheduler(app) -> None:
    global _scheduler_thread
    _runtime.start(
        _scheduler_worker,
        app,
        already_running_message="Allegro Ads scheduler already running",
        started_message="Allegro Ads scheduler thread started",
    )
    _scheduler_thread = _runtime.thread


def stop_allegro_ads_scheduler() -> None:
    global _scheduler_thread
    _runtime.stop(
        stopping_message="Stopping Allegro Ads scheduler...",
        stopped_message="Allegro Ads scheduler stopped",
    )
    _scheduler_thread = None


def run_allegro_ads_sync_now(app) -> dict:
    with app.app_context():
        return sync_ads_panel_statistics()
