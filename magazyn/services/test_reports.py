"""Serwisy testowych akcji raportowych z panelu administracyjnego."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..domain.financial import FinancialCalculator


MONTH_NAMES = [
    "Styczen",
    "Luty",
    "Marzec",
    "Kwiecien",
    "Maj",
    "Czerwiec",
    "Lipiec",
    "Sierpien",
    "Wrzesien",
    "Pazdziernik",
    "Listopad",
    "Grudzien",
]


@dataclass(frozen=True)
class TestReportPayload:
    message: str
    summary: dict


def send_current_month_test_report(session_factory, settings_store, send_report) -> TestReportPayload:
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_ts = int(month_start.timestamp())
    now_ts = int(now.timestamp())
    month_name = MONTH_NAMES[now.month - 1]
    access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")

    with session_factory() as db:
        calculator = FinancialCalculator(db, settings_store)
        period_summary = calculator.get_period_summary(
            month_start_ts,
            now_ts,
            include_fixed_costs=False,
            access_token=access_token,
        )

    summary = {
        "month_name": month_name,
        "products_sold": period_summary.products_sold,
        "total_revenue": float(period_summary.total_revenue),
        "real_profit": float(period_summary.gross_profit),
    }
    message = (
        f"W miesiącu {month_name} sprzedałaś {period_summary.products_sold} produktów "
        f"za {period_summary.total_revenue:.2f} zł co dało {period_summary.gross_profit:.2f} zł zysku"
    )
    send_report("Testowy raport miesieczny", [message])
    return TestReportPayload(message=f"Raport wyslany! Tresc: {message}", summary=summary)


__all__ = ["TestReportPayload", "send_current_month_test_report"]