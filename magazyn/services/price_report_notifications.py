"""Powiadomienia o gotowych raportach cenowych."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import distinct, func

from ..db import get_session
from ..models.price_reports import PriceReport, PriceReportItem
from ..notifications.messenger import MessengerClient, MessengerConfig
from ..settings_store import settings_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportNotificationStats:
    total: int
    cheapest: int
    inna_ok: int
    not_cheapest: int
    errors: int


def send_price_report_notification(report_id: int, *, log: logging.Logger | None = None) -> None:
    """Wyslij powiadomienie Messengerem po zakonczeniu raportu cenowego."""
    active_logger = log or logger
    try:
        stats = _report_summary(report_id)
        if stats is None:
            return

        access_token = settings_store.get("PAGE_ACCESS_TOKEN", "")
        recipient_id = settings_store.get("RECIPIENT_ID", "")
        if not access_token or not recipient_id:
            active_logger.warning("Brak konfiguracji Messenger - pomijam powiadomienie")
            return

        message = _notification_message(report_id, stats)
        client = MessengerClient(MessengerConfig(access_token=access_token, recipient_id=recipient_id))
        if client.send_text(message):
            active_logger.info("Wyslano powiadomienie o raporcie #%s", report_id)
        else:
            active_logger.error("Nie udalo sie wyslac powiadomienia")
    except Exception as exc:
        active_logger.error("Blad wysylania powiadomienia: %s", exc, exc_info=True)


def _count_offers(session, report_id: int, *filters) -> int:
    query = session.query(func.count(distinct(PriceReportItem.offer_id))).filter(
        PriceReportItem.report_id == report_id
    )
    for condition in filters:
        query = query.filter(condition)
    return query.scalar() or 0


def _report_summary(report_id: int) -> ReportNotificationStats | None:
    with get_session() as session:
        report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        if not report:
            return None

        total = _count_offers(session, report_id)
        cheapest = _count_offers(session, report_id, PriceReportItem.is_cheapest.is_(True))
        inna_ok = _count_offers(
            session,
            report_id,
            PriceReportItem.is_cheapest.is_(False),
            PriceReportItem.competitor_price.is_(None),
            PriceReportItem.error.is_(None),
        )
        not_cheapest = _count_offers(
            session,
            report_id,
            PriceReportItem.is_cheapest.is_(False),
            PriceReportItem.competitor_price.isnot(None),
        )
        errors = _count_offers(session, report_id, PriceReportItem.error.isnot(None))

        return ReportNotificationStats(
            total=total,
            cheapest=cheapest,
            inna_ok=inna_ok,
            not_cheapest=not_cheapest,
            errors=errors,
        )


def _notification_message(report_id: int, stats: ReportNotificationStats) -> str:
    lines = [
        f"Raport cenowy #{report_id} gotowy!",
        "",
        f"Sprawdzono: {stats.total} ofert",
        f"Najtansze: {stats.cheapest}",
        f"Inna OK: {stats.inna_ok}",
        f"Drozsi od konkurencji: {stats.not_cheapest}",
    ]
    if stats.errors:
        lines.append(f"Bledy: {stats.errors}")
    lines.extend(["", "Sprawdz szczegoly w aplikacji."])
    return "\n".join(lines)


__all__ = [
    "ReportNotificationStats",
    "send_price_report_notification",
    "_notification_message",
    "_report_summary",
]
