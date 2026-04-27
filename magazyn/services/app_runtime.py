"""Bootstrap procesow tla aplikacji."""

from __future__ import annotations

import atexit
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PrintAgentStartResult:
    started: bool
    failed: bool


def register_shutdown_hooks() -> None:
    from .. import billing_types_scheduler, order_sync_scheduler, promo_scheduler
    from ..print_agent import agent as label_agent

    atexit.register(label_agent.stop_agent_thread)
    atexit.register(order_sync_scheduler.stop_sync_scheduler)
    atexit.register(promo_scheduler.stop_promo_scheduler)
    atexit.register(billing_types_scheduler.stop_billing_types_scheduler)


def start_order_sync_scheduler(app: Any) -> None:
    from .. import order_sync_scheduler

    order_sync_scheduler.start_sync_scheduler(app)


def start_promo_scheduler(app: Any) -> None:
    from .. import promo_scheduler

    promo_scheduler.start_promo_scheduler(app)


def start_billing_types_scheduler(app: Any) -> None:
    from .. import billing_types_scheduler

    billing_types_scheduler.start_billing_types_scheduler(app)


def start_price_report_scheduler(app: Any) -> None:
    from ..price_report_scheduler import start_price_report_scheduler as _start

    _start(app)


def auto_resume_incomplete_price_reports(app: Any) -> None:
    from ..price_report_scheduler import auto_resume_incomplete_reports

    with app.app_context():
        auto_resume_incomplete_reports()


def start_token_refresher() -> None:
    from ..allegro_token_refresher import token_refresher

    token_refresher.start()


def start_dev_token_refresher(app: Any) -> None:
    try:
        start_token_refresher()
    except Exception as exc:
        app.logger.error("Failed to start Allegro token refresher: %s", exc)


def start_print_agent_runtime(app_ctx: Any, agent: Any, config_error_type: type[Exception]) -> PrintAgentStartResult:
    try:
        agent.validate_env()
        agent.ensure_db_init()
        started = agent.start_agent_thread()
    except config_error_type as exc:
        app_ctx.logger.error(f"Failed to start print agent: {exc}")
        return PrintAgentStartResult(started=False, failed=True)
    except Exception as exc:
        app_ctx.logger.error(f"Failed to start print agent: {exc}")
        return PrintAgentStartResult(started=False, failed=True)

    if not started:
        app_ctx.logger.info("Print agent already running")
    return PrintAgentStartResult(started=started, failed=False)


def start_gunicorn_worker_runtime(app: Any, worker_log: Any, worker_pid: int) -> None:
    start_order_sync_scheduler(app)
    worker_log.info(f"Order sync scheduler started in worker {worker_pid}")

    start_price_report_scheduler(app)
    worker_log.info(f"Price report scheduler started in worker {worker_pid}")

    start_promo_scheduler(app)
    worker_log.info(f"Promo scheduler started in worker {worker_pid}")

    start_billing_types_scheduler(app)
    worker_log.info(f"Billing types scheduler started in worker {worker_pid}")

    auto_resume_incomplete_price_reports(app)
    worker_log.info(f"Auto-resume incomplete reports done in worker {worker_pid}")

    start_token_refresher()
    worker_log.info(f"Allegro token refresher started in worker {worker_pid}")


__all__ = [
    "auto_resume_incomplete_price_reports",
    "register_shutdown_hooks",
    "start_billing_types_scheduler",
    "start_dev_token_refresher",
    "start_print_agent_runtime",
    "start_gunicorn_worker_runtime",
    "start_order_sync_scheduler",
    "start_price_report_scheduler",
    "start_promo_scheduler",
    "start_token_refresher",
]