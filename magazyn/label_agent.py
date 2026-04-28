from __future__ import annotations

import logging
import threading

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type, TypeVar
from zoneinfo import ZoneInfo

from .config import load_config
from .domain.inventory import consume_order_stock as _consume_order_stock
from .notifications import send_report as _send_report
from .services.print_agent_config import (
    AgentConfig,
    ConfigError,
)
from .services import label_agent_integrations as integrations
from .services import label_agent_loop as loop_services
from .services.print_agent_lifecycle import (
    start_agent_thread as _start_agent_thread,
    stop_agent_thread as _stop_agent_thread,
)
from .services.print_agent_notifications import PrintAgentNotifier, notify_messenger
from .services.print_agent_retry import enforce_rate_limit, new_call_window, retry_call
from .services.print_agent_storage import PrintAgentStorage, SuccessMarker
from .services.print_agent_tracking import PrintAgentTrackingService
from .services.printing import CupsPrinter
from .services.runtime import BackgroundThreadRuntime, HeartbeatFileLock
from .allegro_token_refresher import token_refresher
from .allegro_api.shipment_management import (
    cancel_shipment,
    create_shipment,
    get_delivery_services,
    get_shipment_details,
    get_shipment_label,
    wait_for_shipment_creation,
)
from .allegro_api.fulfillment import (
    add_shipment_tracking,
    update_fulfillment_status,
)
from .workers import TrackingWorker, MessagingWorker, ReportWorker
from .metrics import (
    PRINT_AGENT_DOWNTIME_SECONDS,
    PRINT_AGENT_RETRIES_TOTAL,
    PRINT_LABEL_ERRORS_TOTAL,
    PRINT_LABELS_TOTAL,
)


T = TypeVar("T")


# Uzywamy short_preview z modulu utils


class LabelAgent:
    """Encapsulates the state and behaviour of the label printing agent."""

    def __init__(self, config: AgentConfig, settings_obj: Any):
        self.config = config
        self.settings = settings_obj
        self.logger = logging.getLogger(__name__)
        self.last_order_data: Dict[str, Any] = {}
        self._thread_runtime = BackgroundThreadRuntime(
            name="LabelAgent",
            logger=self.logger,
        )
        self._agent_thread: Optional[threading.Thread] = None
        self._stop_event = self._thread_runtime.stop_event
        self._rate_limit_lock = threading.Lock()
        self._lock_handle = None
        self._heartbeat_lock = HeartbeatFileLock(
            lock_file_provider=lambda: self.config.lock_file,
            poll_interval_provider=lambda: self.config.poll_interval,
            logger=self.logger,
            stale_warning="Wyczyszczono porzuconą blokadę agenta drukowania",
        )
        self._api_calls_total = 0
        self._api_calls_success = 0
        self._last_api_log = datetime.now()
        self._api_call_times = new_call_window()
        self._workers: List = []
        self.notifier = PrintAgentNotifier(
            logger=self.logger,
            config_provider=lambda: self.config,
        )
        self.consume_order_stock = _consume_order_stock
        self.send_report = _send_report
        self._label_error_notifications = self.notifier.error_counts
        self.storage = PrintAgentStorage(
            logger=self.logger,
            now=lambda: datetime.now(),
            handle_readonly_error=self._handle_readonly_error,
        )
        self.printer = CupsPrinter(
            printer_name=config.printer_name,
            cups_server=config.cups_server,
            cups_port=config.cups_port,
        )
        self._configure_logging(initial=True)
        self._configure_db_engine()

    @property
    def _heartbeat_path(self) -> str:
        return self._heartbeat_lock.heartbeat_path

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _configure_logging(self, initial: bool = False) -> None:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.config.log_level, logging.INFO))

        # Ensure we have a stream handler for console output.
        if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            root_logger.addHandler(stream_handler)

        # Replace existing file handlers so updates to LOG_FILE take effect.
        file_handlers = [h for h in root_logger.handlers if isinstance(h, logging.FileHandler)]
        for handler in file_handlers:
            root_logger.removeHandler(handler)
            handler.close()
        file_handler = logging.FileHandler(self.config.log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        self.logger.setLevel(getattr(logging, self.config.log_level, logging.INFO))
        if initial:
            self.logger.debug("LabelAgent logging configured")

    def _configure_db_engine(self) -> None:
        from . import db

        db.configure_engine(self.config.db_file)

    @staticmethod
    def _is_readonly_error(exc: Exception) -> bool:
        return "readonly" in str(exc).lower() or "read-only" in str(exc).lower()

    def _handle_readonly_error(self, action: str, exc: Exception) -> bool:
        if self._is_readonly_error(exc):
            self.logger.warning(
                "Database is read-only; skipping %s: %s",
                action,
                exc,
            )
            return True
        return False

    def reload_config(self) -> None:
        """Reload configuration from ``.env`` and update the agent state."""
        self.settings = load_config()
        self.config = AgentConfig.from_settings(self.settings)
        self._configure_logging()
        self._configure_db_engine()

    # Backwards-compatible alias
    reload_env = reload_config

    # ------------------------------------------------------------------
    # Validation and persistence helpers
    # ------------------------------------------------------------------
    def _read_heartbeat(self) -> Optional[datetime]:
        return self._heartbeat_lock.read_heartbeat()

    def _write_heartbeat(self) -> None:
        self._heartbeat_lock.write_heartbeat()

    def _clear_heartbeat(self) -> None:
        self._heartbeat_lock.clear_heartbeat()

    def _cleanup_orphaned_lock(self) -> None:
        self._heartbeat_lock.cleanup_orphaned_lock()

    def _restore_in_progress(self, queue: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        restored = False
        for item in queue:
            if item.get("status") == "in_progress":
                item["status"] = "queued"
                restored = True
        if restored:
            self.save_queue(queue)
        return queue

    def _retry(
        self,
        func: Callable[..., T],
        *args: Any,
        stage: str,
        retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
        max_attempts: int = 3,
        base_delay: float = 1.0,
        **kwargs: Any,
    ) -> T:
        return retry_call(
            func,
            *args,
            stage=stage,
            stop_event=self._stop_event,
            retry_metric=PRINT_AGENT_RETRIES_TOTAL,
            downtime_metric=PRINT_AGENT_DOWNTIME_SECONDS,
            logger=self.logger,
            retry_exceptions=retry_exceptions,
            max_attempts=max_attempts,
            base_delay=base_delay,
            **kwargs,
        )

    def validate_env(self) -> None:
        required = {
            "PAGE_ACCESS_TOKEN": self.config.page_access_token,
            "RECIPIENT_ID": self.config.recipient_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            self.logger.error(
                "Brak wymaganych zmiennych środowiskowych: %s", ", ".join(missing)
            )
            raise ConfigError("Missing environment variables: " + ", ".join(missing))

    def ensure_db(self) -> None:
        self.storage.ensure_db()

    def ensure_db_init(self) -> None:
        self.ensure_db()

    def load_printed_orders(self) -> List[Dict[str, Any]]:
        return self.storage.load_printed_orders()

    def mark_as_printed(
        self, order_id: str, last_order_data: Optional[Dict[str, Any]] = None
    ) -> None:
        self.storage.mark_as_printed(order_id, last_order_data)

    def _load_state_value(self, key: str) -> Optional[str]:
        return self.storage.load_state_value(key)

    def _save_state_value(self, key: str, value: Optional[str]) -> None:
        self.storage.save_state_value(key, value)

    def load_last_success_marker(self) -> SuccessMarker:
        return self.storage.load_last_success_marker()

    def update_last_success_marker(
        self, order_id: Optional[str], timestamp: Optional[str] = None
    ) -> None:
        self.storage.update_last_success_marker(order_id, timestamp)

    def clean_old_printed_orders(self) -> None:
        self.storage.clean_old_printed_orders(self.config.printed_expiry_days)

    def _deduplicate_queue(self, queue: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self.storage.deduplicate_queue(queue)

    def _update_queue_metrics(self, queue: Iterable[Dict[str, Any]]) -> None:
        return self.storage.update_queue_metrics(queue)

    def load_queue(self) -> List[Dict[str, Any]]:
        return self.storage.load_queue()

    def save_queue(self, items: Iterable[Dict[str, Any]]) -> None:
        self.storage.save_queue(items)

    # ------------------------------------------------------------------
    # External integrations
    # ------------------------------------------------------------------
    def _maybe_log_api_summary(self) -> None:
        integrations.maybe_log_api_summary(self)

    def _enforce_rate_limit(self) -> None:
        enforce_rate_limit(
            max_calls=max(0, self.config.api_rate_limit_calls),
            window=self.config.api_rate_limit_period,
            call_times=self._api_call_times,
            lock=self._rate_limit_lock,
            stop_event=self._stop_event,
            downtime_metric=PRINT_AGENT_DOWNTIME_SECONDS,
            logger=self.logger,
        )

    def get_orders(self) -> List[Dict[str, Any]]:
        return integrations.get_orders(self)

    def get_order_packages(self, order_id: str) -> List[Dict[str, Any]]:
        return integrations.get_order_packages(
            self,
            order_id,
            get_shipment_details=get_shipment_details,
            create_allegro_shipment=self._create_allegro_shipment,
        )

    def _create_allegro_shipment(
        self, order_id: str, checkout_form_id: str,
    ) -> List[Dict[str, Any]]:
        return integrations.create_allegro_shipment(self, order_id, checkout_form_id)

    def _shipment_creator(self):
        return integrations.shipment_creator(
            self,
            create_shipment=create_shipment,
            wait_for_shipment_creation=wait_for_shipment_creation,
            get_shipment_details=get_shipment_details,
            add_shipment_tracking=add_shipment_tracking,
            update_fulfillment_status=update_fulfillment_status,
        )

    def _resolve_delivery_service_id(self, delivery_method: str) -> Optional[str]:
        return integrations.resolve_delivery_service_id(
            self,
            delivery_method,
            get_delivery_services=get_delivery_services,
        )

    def _resolve_carrier_id(self, delivery_method: str) -> Optional[str]:
        return integrations.resolve_carrier_id(delivery_method)

    def _label_service(self):
        return integrations.label_service(
            self,
            get_shipment_label=get_shipment_label,
            cancel_shipment=cancel_shipment,
            create_shipment=self._create_allegro_shipment,
            label_errors_total=PRINT_LABEL_ERRORS_TOTAL,
        )

    def _collect_order_labels(
        self,
        order_id: str,
        packages: List[Dict[str, Any]],
    ):
        return integrations.collect_order_labels(self, order_id, packages)

    def _recreate_shipment_and_get_label(
        self,
        order_id: str,
        old_shipment_id: str,
        courier_code: str,
        package_ids: List[str],
        tracking_numbers: List[str],
    ) -> Tuple[str, str]:
        return integrations.recreate_shipment_and_get_label(
            self,
            order_id,
            old_shipment_id,
            courier_code,
            package_ids,
            tracking_numbers,
        )

    def get_label(self, courier_code: str, package_id: str) -> Tuple[str, str]:
        return integrations.get_label(self, courier_code, package_id)

    def print_label(self, base64_data: str, extension: str, order_id: str) -> None:
        integrations.print_label(
            self,
            base64_data,
            extension,
            order_id,
            labels_total=PRINT_LABELS_TOTAL,
            errors_total=PRINT_LABEL_ERRORS_TOTAL,
        )

    def print_test_page(self) -> bool:
        return integrations.print_test_page(self)

    def _should_send_error_notification(self, order_id: str) -> bool:
        """Sprawdza czy należy wysłać powiadomienie o błędzie (przy próbie 1 i 10)."""
        return self.notifier.should_send_error_notification(order_id)

    def _send_label_error_notification(self, order_id: str) -> None:
        """Wysyła krótkie powiadomienie o braku etykiety."""
        self.notifier.send_label_error_notification(order_id)

    def send_messenger_message(self, data: Dict[str, Any], print_success: bool = True) -> None:
        self.notifier.send_messenger_message(data, print_success=print_success)

    # ------------------------------------------------------------------
    # Tracking status updates (Allegro API)
    # ------------------------------------------------------------------
    # Allegro tracking event type -> our internal status (imported from status_config)
    from .status_config import ALLEGRO_TRACKING_MAP as ALLEGRO_TRACKING_STATUS_MAP

    def _check_tracking_statuses(self) -> None:
        """Sprawdz i zaktualizuj statusy przesylek przez Allegro Tracking API."""
        service = PrintAgentTrackingService(
            logger=self.logger,
            resolve_carrier_id=self._resolve_carrier_id,
            tracking_map=self.ALLEGRO_TRACKING_STATUS_MAP,
        )
        service.check_tracking_statuses()

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------
    def is_quiet_time(self) -> bool:
        now = datetime.now(ZoneInfo(self.config.timezone)).time()
        start = self.config.quiet_hours_start
        end = self.config.quiet_hours_end
        if start <= end:
            return start <= now < end
        return now >= start or now < end

    def _report_service(self):
        return loop_services.report_service(self)

    def _send_periodic_reports(self) -> None:
        loop_services.send_periodic_reports(self)
    
    def _get_period_summary(self, days: int, end_date: datetime = None, include_fixed_costs: bool = False) -> dict:
        return loop_services.get_period_summary(self, days, end_date, include_fixed_costs)

    def _process_queue(self, queue: List[Dict[str, Any]], printed: Dict[str, Any]) -> List[Dict[str, Any]]:
        return loop_services.process_queue(self, queue, printed)

    def _order_processor(self):
        return loop_services.order_processor(self)

    def _check_allegro_discussions(self, access_token: str) -> None:
        loop_services.check_allegro_discussions(self, access_token)

    def _check_allegro_messages(self, access_token: str) -> None:
        loop_services.check_allegro_messages(self, access_token)

    def _agent_loop(self) -> None:
        loop_services.agent_loop(self)

    def _run_print_iteration(self) -> None:
        loop_services.run_print_iteration(self)

    def start_agent_thread(self) -> bool:
        return _start_agent_thread(
            self,
            worker_factories=(TrackingWorker, MessagingWorker, ReportWorker),
        )

    def _notify_messenger(self, data: Dict[str, Any], print_success: bool) -> None:
        """Call ``send_messenger_message`` while tolerating simplified monkeypatches."""
        notify_messenger(self.send_messenger_message, data, print_success)

    def stop_agent_thread(self) -> None:
        _stop_agent_thread(self, token_refresher=token_refresher)


__all__ = ["LabelAgent"]

