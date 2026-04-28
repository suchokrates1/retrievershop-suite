"""Petla pracy i raporty runtime agenta etykiet."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from ..agent.allegro_sync import AllegroSyncService
from ..metrics import PRINT_AGENT_ITERATION_SECONDS, PRINT_LABEL_ERRORS_TOTAL
from .print_agent_errors import ApiError, PrintError
from .print_agent_order_processor import PrintOrderProcessor
from .print_agent_queue import PrintQueueProcessor
from .print_agent_reports import PrintAgentReportService


def report_service(agent) -> PrintAgentReportService:
    return PrintAgentReportService(
        logger=agent.logger,
        config_provider=lambda: agent.config,
        send_report=agent.send_report,
        summary_provider=agent._get_period_summary,
        get_last_weekly_report=lambda: getattr(agent, "_last_weekly_report", None),
        set_last_weekly_report=lambda value: setattr(agent, "_last_weekly_report", value),
        get_last_monthly_report_month=lambda: getattr(agent, "_last_monthly_report_month", None),
        set_last_monthly_report_month=lambda value: setattr(
            agent,
            "_last_monthly_report_month",
            value,
        ),
    )


def send_periodic_reports(agent) -> None:
    report_service(agent).send_periodic_reports()


def get_period_summary(agent, days: int, end_date: datetime = None, include_fixed_costs: bool = False) -> dict:
    return report_service(agent).get_period_summary(
        days,
        end_date=end_date,
        include_fixed_costs=include_fixed_costs,
    )


def process_queue(agent, queue: List[Dict[str, Any]], printed: Dict[str, Any]) -> List[Dict[str, Any]]:
    processor = PrintQueueProcessor(
        logger=agent.logger,
        is_quiet_time=agent.is_quiet_time,
        save_queue=agent.save_queue,
        mark_as_printed=agent.mark_as_printed,
        notify_messenger=agent._notify_messenger,
        retry=agent._retry,
        print_label=agent.print_label,
        consume_order_stock=agent.consume_order_stock,
        print_error_type=PrintError,
        errors_total=PRINT_LABEL_ERRORS_TOTAL,
        now=lambda: datetime.now(),
    )
    return processor.process(queue, printed)


def order_processor(agent) -> PrintOrderProcessor:
    return PrintOrderProcessor(
        logger=agent.logger,
        set_last_order_data=lambda data: setattr(agent, "last_order_data", data),
        retry=agent._retry,
        get_order_packages=agent.get_order_packages,
        collect_order_labels=agent._collect_order_labels,
        is_quiet_time=agent.is_quiet_time,
        save_queue=agent.save_queue,
        print_label=agent.print_label,
        mark_as_printed=agent.mark_as_printed,
        notify_messenger=agent._notify_messenger,
        consume_order_stock=agent.consume_order_stock,
        should_send_error_notification=agent._should_send_error_notification,
        send_label_error_notification=agent._send_label_error_notification,
        increment_error_notification=agent.notifier.increment_error_notification,
        wait=agent._stop_event.wait,
        errors_total=PRINT_LABEL_ERRORS_TOTAL,
        print_error_type=PrintError,
        now=lambda: datetime.now(),
    )


def check_allegro_discussions(agent, access_token: str) -> None:
    service = AllegroSyncService(
        db_file=agent.config.db_file,
        settings=agent.settings,
        save_state_callback=agent._save_state_value,
    )
    service.check_discussions(access_token)


def check_allegro_messages(agent, access_token: str) -> None:
    service = AllegroSyncService(
        db_file=agent.config.db_file,
        settings=agent.settings,
        save_state_callback=agent._save_state_value,
    )
    service.check_messages(access_token)


def agent_loop(agent) -> None:
    while not agent._stop_event.is_set():
        try:
            run_print_iteration(agent)
        except Exception as exc:
            agent.logger.error("[BLAD ITERACJI GLOWNEJ] %s", exc, exc_info=True)
            PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
        agent._stop_event.wait(agent.config.poll_interval)


def run_print_iteration(agent) -> None:
    loop_start = datetime.now()
    agent._write_heartbeat()
    agent.clean_old_printed_orders()
    printed_entries = agent.load_printed_orders()
    printed = {entry["order_id"]: entry["printed_at"] for entry in printed_entries}
    queue = agent.load_queue()
    queue = agent._restore_in_progress(queue)
    queue = agent._process_queue(queue, printed)
    agent.save_queue(queue)

    try:
        try:
            orders = agent._retry(
                agent.get_orders,
                stage="orders",
                retry_exceptions=(ApiError,),
            )
        except ApiError as exc:
            agent.logger.error("Blad pobierania zamowien: %s", exc)
            PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
            orders = []
        processor = agent._order_processor()
        for order in orders:
            processor.process(order, queue, printed)
    except Exception as exc:
        agent.logger.error("[BLAD PETLI ZAMOWIEN] %s", exc)
        PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()

    agent.save_queue(queue)
    duration = (datetime.now() - loop_start).total_seconds()
    PRINT_AGENT_ITERATION_SECONDS.observe(duration)
    agent._write_heartbeat()


__all__ = [
    "agent_loop",
    "check_allegro_discussions",
    "check_allegro_messages",
    "get_period_summary",
    "order_processor",
    "process_queue",
    "report_service",
    "run_print_iteration",
    "send_periodic_reports",
]