"""Raporty okresowe wysylane przez agenta drukowania."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Tuple


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


class PrintAgentReportService:
    """Obsluga tygodniowych i miesiecznych raportow sprzedazy."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        config_provider: Callable[[], Any],
        send_report: Callable[[str, list[str]], None],
        summary_provider: Callable[..., Optional[Dict[str, Any]]],
        get_last_weekly_report: Callable[[], Optional[datetime]],
        set_last_weekly_report: Callable[[datetime], None],
        get_last_monthly_report_month: Callable[[], Optional[Tuple[int, int]]],
        set_last_monthly_report_month: Callable[[Tuple[int, int]], None],
        now: Callable[[], datetime] = datetime.now,
    ):
        self.logger = logger
        self.config_provider = config_provider
        self.send_report = send_report
        self.summary_provider = summary_provider
        self.get_last_weekly_report = get_last_weekly_report
        self.set_last_weekly_report = set_last_weekly_report
        self.get_last_monthly_report_month = get_last_monthly_report_month
        self.set_last_monthly_report_month = set_last_monthly_report_month
        self.now = now

    def send_periodic_reports(self) -> None:
        current_time = self.now()
        config = self.config_provider()
        self._send_weekly_report(config, current_time)
        self._send_monthly_report(config, current_time)

    def get_period_summary(
        self,
        days: int,
        end_date: Optional[datetime] = None,
        include_fixed_costs: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if end_date is None:
            end_date = datetime.now()

        start_date = end_date - timedelta(days=days)
        start_ts = int(
            start_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        )
        end_ts = int(
            end_date.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
        )

        try:
            from ..db import get_session
            from ..domain.financial import FinancialCalculator
            from ..settings_store import settings_store

            access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
            with get_session() as db:
                calculator = FinancialCalculator(db, settings_store)
                summary = calculator.get_period_summary(
                    start_ts,
                    end_ts,
                    include_fixed_costs=include_fixed_costs,
                    access_token=access_token,
                )

                result = {
                    "products_sold": summary.products_sold,
                    "total_revenue": float(summary.total_revenue),
                    "real_profit": float(
                        summary.net_profit if include_fixed_costs else summary.gross_profit
                    ),
                }
                if include_fixed_costs:
                    result["profit_before_fixed"] = float(summary.gross_profit)
                    result["fixed_costs"] = float(summary.fixed_costs)
                    result["fixed_costs_list"] = summary.fixed_costs_list
                return result
        except Exception as exc:
            self.logger.error("Blad pobierania podsumowania sprzedazy: %s", exc)
            return None

    def _send_weekly_report(self, config: Any, current_time: datetime) -> None:
        last_weekly_report = self.get_last_weekly_report()
        if not config.enable_weekly_reports:
            return
        if last_weekly_report and current_time - last_weekly_report < timedelta(days=7):
            return

        summary = self.summary_provider(days=7)
        if not summary:
            return

        message = (
            f"W tym tygodniu sprzedałaś {summary['products_sold']} produktów "
            f"za {summary['total_revenue']:.2f} zł co dało "
            f"{summary['real_profit']:.2f} zł zysku"
        )
        self.send_report("Raport tygodniowy", [message])
        self.set_last_weekly_report(current_time)

    def _send_monthly_report(self, config: Any, current_time: datetime) -> None:
        if not config.enable_monthly_reports or current_time.day != 1:
            return

        current_month = (current_time.year, current_time.month)
        if self.get_last_monthly_report_month() == current_month:
            return

        previous_month_end = current_time.replace(day=1) - timedelta(days=1)
        previous_month_start = previous_month_end.replace(day=1)
        days_in_previous_month = (previous_month_end - previous_month_start).days + 1
        month_name = MONTH_NAMES[previous_month_end.month - 1]

        summary = self.summary_provider(
            days=days_in_previous_month,
            end_date=previous_month_end,
            include_fixed_costs=True,
        )
        if not summary:
            return

        fixed_info = ""
        if summary.get("fixed_costs", 0) > 0:
            fixed_info = f" (po odliczeniu {summary['fixed_costs']:.0f} zł kosztów stałych)"
        message = (
            f"W miesiącu {month_name} sprzedałaś {summary['products_sold']} produktów "
            f"za {summary['total_revenue']:.2f} zł co dało "
            f"{summary['real_profit']:.2f} zł zysku{fixed_info}"
        )
        self.send_report("Raport miesieczny", [message])
        self.set_last_monthly_report_month(current_month)


__all__ = ["MONTH_NAMES", "PrintAgentReportService"]