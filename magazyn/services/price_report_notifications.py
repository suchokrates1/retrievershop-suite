"""Powiadomienia o gotowych raportach cenowych."""

from __future__ import annotations

import logging

from sqlalchemy import distinct, func

from ..db import get_session
from ..models.price_reports import PriceReport, PriceReportItem
from ..notifications.messenger import MessengerClient, MessengerConfig
from ..settings_store import settings_store

logger = logging.getLogger(__name__)


def send_price_report_notification(report_id: int, *, log: logging.Logger | None = None) -> None:
    """Wyslij powiadomienie Messengerem po zakonczeniu raportu cenowego."""
    active_logger = log or logger
    try:
        total, cheapest = _report_summary(report_id)
        if total is None:
            return

        access_token = settings_store.get("PAGE_ACCESS_TOKEN", "")
        recipient_id = settings_store.get("RECIPIENT_ID", "")
        if not access_token or not recipient_id:
            active_logger.warning("Brak konfiguracji Messenger - pomijam powiadomienie")
            return

        message = _notification_message(report_id, total, cheapest)
        client = MessengerClient(MessengerConfig(access_token=access_token, recipient_id=recipient_id))
        if client.send_text(message):
            active_logger.info("Wyslano powiadomienie o raporcie #%s", report_id)
        else:
            active_logger.error("Nie udalo sie wyslac powiadomienia")
    except Exception as exc:
        active_logger.error("Blad wysylania powiadomienia: %s", exc, exc_info=True)


def _report_summary(report_id: int) -> tuple[int | None, int]:
    with get_session() as session:
        report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        if not report:
            return None, 0

        total = (
            session.query(func.count(distinct(PriceReportItem.offer_id)))
            .filter(PriceReportItem.report_id == report_id)
            .scalar()
            or 0
        )
        cheapest = (
            session.query(func.count(distinct(PriceReportItem.offer_id)))
            .filter(
                PriceReportItem.report_id == report_id,
                PriceReportItem.is_cheapest.is_(True),
            )
            .scalar()
            or 0
        )
        return total, cheapest


def _notification_message(report_id: int, total: int, cheapest: int) -> str:
    not_cheapest = total - cheapest
    return (
        f"Raport cenowy #{report_id} gotowy!\n\n"
        f"Sprawdzono: {total} ofert\n"
        f"Najtansi: {cheapest}\n"
        f"Drozsi od konkurencji: {not_cheapest}\n\n"
        f"Sprawdz szczegoly w aplikacji."
    )


__all__ = ["send_price_report_notification"]