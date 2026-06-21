from decimal import Decimal

from magazyn.db import get_session
from magazyn.models.price_reports import PriceReport, PriceReportItem
from magazyn.services.price_report_notifications import (
    ReportNotificationStats,
    _notification_message,
    _report_summary,
)


def _add_item(session, report_id, offer_id, *, is_cheapest=True, competitor_price=None, error=None):
    session.add(
        PriceReportItem(
            report_id=report_id,
            offer_id=offer_id,
            our_price=Decimal("100.00"),
            is_cheapest=is_cheapest,
            competitor_price=competitor_price,
            error=error,
        )
    )


def test_report_summary_splits_inna_ok_from_not_cheapest(app):
    with app.app_context():
        with get_session() as session:
            report = PriceReport(status="completed", items_total=5, items_checked=5)
            session.add(report)
            session.flush()

            _add_item(session, report.id, "offer-cheapest", is_cheapest=True, competitor_price=Decimal("90.00"))
            _add_item(
                session,
                report.id,
                "offer-inna-ok",
                is_cheapest=False,
                competitor_price=None,
            )
            _add_item(
                session,
                report.id,
                "offer-expensive",
                is_cheapest=False,
                competitor_price=Decimal("80.00"),
            )
            _add_item(
                session,
                report.id,
                "offer-error",
                is_cheapest=False,
                competitor_price=None,
                error="timeout",
            )
            session.commit()
            report_id = report.id

        stats = _report_summary(report_id)
        assert stats == ReportNotificationStats(
            total=4,
            cheapest=1,
            inna_ok=1,
            not_cheapest=1,
            errors=1,
        )


def test_notification_message_includes_inna_ok_line(app):
    stats = ReportNotificationStats(
        total=10,
        cheapest=5,
        inna_ok=2,
        not_cheapest=2,
        errors=1,
    )
    message = _notification_message(42, stats)

    assert "Inna OK: 2" in message
    assert "Drozsi od konkurencji: 2" in message
    assert "Drozsi od konkurencji: 5" not in message
    assert "Bledy: 1" in message
