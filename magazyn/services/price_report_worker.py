"""Worker przetwarzania raportow cenowych."""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Callable, List


def run_report_worker(
    app,
    report_id: int,
    schedule: List[datetime],
    *,
    fast_mode: bool,
    stop_event,
    log,
    batch_size: int,
    manual_min_batch_delay: int,
    manual_max_batch_delay: int,
    night_pause_end: int,
    is_night_pause: Callable[[], bool],
    mark_sibling_offers: Callable[[int], int],
    get_unchecked_offers: Callable[[int, int], list[dict]],
    check_single_offer: Callable[..., object],
    save_report_item: Callable[[int, dict], object],
    finalize_report: Callable[[int], object],
    send_report_notification: Callable[[int], object],
    cdp_host: str,
    cdp_port: int,
) -> None:
    """Przetworz raport cenowy partiami."""
    mode_label = "reczny" if fast_mode else "wolny"
    log.info(
        "Rozpoczynam przetwarzanie raportu #%s, %s partii (tryb: %s)",
        report_id,
        len(schedule),
        mode_label,
    )

    _mark_sibling_offers(app, report_id, mark_sibling_offers, log)
    batch_index = 0
    while not stop_event.is_set() and batch_index < len(schedule):
        if not fast_mode and not _wait_for_scheduled_batch(
            schedule[batch_index],
            batch_index,
            stop_event,
            is_night_pause,
            night_pause_end,
            log,
        ):
            break

        has_offers = _process_batch(
            app,
            report_id,
            batch_index,
            stop_event,
            log,
            batch_size,
            get_unchecked_offers,
            check_single_offer,
            save_report_item,
            cdp_host,
            cdp_port,
        )
        if not has_offers:
            break
        batch_index += 1

        if fast_mode and not stop_event.is_set() and batch_index < len(schedule):
            delay = random.uniform(manual_min_batch_delay, manual_max_batch_delay)  # nosec B311
            log.info("Tryb reczny: czekam %.1f min do nastepnej partii", delay / 60)
            stop_event.wait(delay)

    _finalize_and_notify(app, report_id, finalize_report, send_report_notification, log)
    log.info("Zakonczono przetwarzanie raportu #%s", report_id)


def _mark_sibling_offers(app, report_id: int, mark_sibling_offers, log) -> None:
    try:
        with app.app_context():
            sibling_count = mark_sibling_offers(report_id)
            if sibling_count > 0:
                log.info("Pominiento %s ofert (Inna OK) - zostaly drozsze siostry", sibling_count)
    except Exception as exc:
        log.warning("Blad oznaczania siostrzanych ofert: %s", exc)


def _wait_for_scheduled_batch(
    target_time: datetime,
    batch_index: int,
    stop_event,
    is_night_pause: Callable[[], bool],
    night_pause_end: int,
    log,
) -> bool:
    now = datetime.now()
    if now < target_time:
        wait_seconds = (target_time - now).total_seconds()
        log.info("Czekam %.1f min do partii %s", wait_seconds / 60, batch_index + 1)
        if stop_event.wait(wait_seconds):
            log.info("Przerwano oczekiwanie")
            return False

    if is_night_pause():
        log.info("Przerwa nocna - czekam do 06:00")
        now = datetime.now()
        wake_time = now.replace(hour=night_pause_end, minute=0, second=0)
        if now.hour >= night_pause_end:
            wake_time += timedelta(days=1)
        if stop_event.wait((wake_time - now).total_seconds()):
            return False
    return True


def _process_batch(
    app,
    report_id: int,
    batch_index: int,
    stop_event,
    log,
    batch_size: int,
    get_unchecked_offers,
    check_single_offer,
    save_report_item,
    cdp_host: str,
    cdp_port: int,
) -> bool:
    try:
        with app.app_context():
            offers = get_unchecked_offers(report_id, batch_size)
            if not offers:
                log.info("Brak wiecej ofert do sprawdzenia")
                return False

            log.info("Partia %s: sprawdzam %s ofert", batch_index + 1, len(offers))
            for offer in offers:
                if stop_event.is_set():
                    break
                _check_offer(report_id, offer, log, check_single_offer, save_report_item, cdp_host, cdp_port)
            return True
    except Exception as exc:
        log.error("Blad partii %s: %s", batch_index + 1, exc, exc_info=True)
        return True


def _check_offer(report_id: int, offer: dict, log, check_single_offer, save_report_item, cdp_host: str, cdp_port: int) -> None:
    try:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(check_single_offer(offer, cdp_host, cdp_port))
        finally:
            loop.close()

        save_report_item(report_id, result)
        log.info("Sprawdzono: %s - %s", offer["offer_id"], "OK" if result["success"] else result["error"])
        time.sleep(random.uniform(2, 5))  # nosec B311
    except Exception as exc:
        log.error("Blad sprawdzania oferty %s: %s", offer["offer_id"], exc)
        save_report_item(
            report_id,
            {
                **offer,
                "success": False,
                "error": str(exc),
                "my_position": 0,
                "competitors_count": 0,
                "cheapest": None,
            },
        )


def _finalize_and_notify(app, report_id: int, finalize_report, send_report_notification, log) -> None:
    with app.app_context():
        finalize_report(report_id)
        now = datetime.now()
        if now.weekday() == 6 and now.hour < 16:
            wait_until_16 = (now.replace(hour=16, minute=0, second=0) - now).total_seconds()
            if wait_until_16 > 0:
                log.info("Czekam %.1f min na wyslanie powiadomienia", wait_until_16 / 60)
                time.sleep(wait_until_16)
        send_report_notification(report_id)


__all__ = ["run_report_worker"]