from __future__ import annotations

import logging
import threading
import time

from collections import deque
from datetime import datetime, timedelta
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple, Type, TypeVar
from zoneinfo import ZoneInfo

from .config import load_config, settings
from .notifications import send_report
from .parsing import parse_product_info  # noqa: F401 - publiczny re-export magazyn.print_agent
from .services import consume_order_stock, get_sales_summary  # noqa: F401
from .services.print_agent_config import (
    AgentConfig,
    ConfigError,
    calculate_cod_amount,  # noqa: F401 - publiczny re-export magazyn.print_agent
    parse_time_str,
)
from .services.print_agent_delivery import resolve_delivery_service_id
from .services.print_agent_errors import ApiError, PrintError, ShipmentExpiredError
from .services.print_agent_labels import CollectedLabels, PrintLabelService
from .services.print_agent_notifications import PrintAgentNotifier, notify_messenger
from .services.print_agent_order_processor import PrintOrderProcessor
from .services.print_agent_queue import PrintQueueProcessor
from .services.print_agent_reports import PrintAgentReportService
from .services.print_agent_shipment_creation import PrintShipmentCreator
from .services.print_agent_storage import PrintAgentStorage, SuccessMarker
from .services.print_agent_shipments import (
    resolve_carrier_id,
    shorten_product_name,
)
from .services.print_agent_tracking import PrintAgentTrackingService
from .services.printing import CupsPrinter, PrintCommandError
from .services.runtime import BackgroundThreadRuntime, HeartbeatFileLock
from .allegro_token_refresher import token_refresher
from .allegro_api import (
    fetch_allegro_order_detail,
)
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
from .agent.allegro_sync import AllegroSyncService
from .workers import TrackingWorker, MessagingWorker, ReportWorker
from .metrics import (
    PRINT_AGENT_DOWNTIME_SECONDS,
    PRINT_AGENT_ITERATION_SECONDS,
    PRINT_AGENT_RETRIES_TOTAL,
    PRINT_QUEUE_OLDEST_AGE_SECONDS,  # noqa: F401 - publiczny re-export magazyn.print_agent
    PRINT_QUEUE_SIZE,  # noqa: F401 - publiczny re-export magazyn.print_agent
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
        self._api_call_times: Deque[float] = deque()
        self._workers: List = []
        self.notifier = PrintAgentNotifier(
            logger=self.logger,
            config_provider=lambda: self.config,
        )
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
        globals()["settings"] = self.settings
        globals()["logger"] = self.logger

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
        attempts = 0
        while True:
            try:
                return func(*args, **kwargs)
            except ShipmentExpiredError:
                raise
            except retry_exceptions as exc:
                attempts += 1
                if attempts >= max_attempts or self._stop_event.is_set():
                    raise
                delay = base_delay * (2 ** (attempts - 1))
                self.logger.warning(
                    "%s failed (%s). Retrying in %.1fs (attempt %s/%s)",
                    stage,
                    exc,
                    delay,
                    attempts + 1,
                    max_attempts,
                )
                PRINT_AGENT_RETRIES_TOTAL.inc()
                PRINT_AGENT_DOWNTIME_SECONDS.inc(delay)
                if self._stop_event.wait(delay):
                    raise

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
        now = datetime.now()
        if now - self._last_api_log >= timedelta(hours=1) and self._api_calls_total:
            self.logger.info(
                "Udane połączenia: [%s/%s]",
                self._api_calls_success,
                self._api_calls_total,
            )
            self._api_calls_total = 0
            self._api_calls_success = 0
            self._last_api_log = now

    def _enforce_rate_limit(self) -> None:
        max_calls = max(0, self.config.api_rate_limit_calls)
        window = self.config.api_rate_limit_period
        if max_calls <= 0 or window <= 0:
            return
        with self._rate_limit_lock:
            now = time.monotonic()
            while self._api_call_times and now - self._api_call_times[0] >= window:
                self._api_call_times.popleft()
            if len(self._api_call_times) >= max_calls:
                wait_until = self._api_call_times[0] + window
                wait_time = wait_until - now
                if wait_time > 0:
                    self.logger.debug(
                        "Rate limit reached, waiting %.2fs before next API call",
                        wait_time,
                    )
                    PRINT_AGENT_DOWNTIME_SECONDS.inc(wait_time)
                    if self._stop_event.wait(wait_time):
                        raise ApiError("Rate limit wait interrupted")
                now = time.monotonic()
                while self._api_call_times and now - self._api_call_times[0] >= window:
                    self._api_call_times.popleft()
            self._api_call_times.append(time.monotonic())

    def get_orders(self) -> List[Dict[str, Any]]:
        """Pobierz zamowienia gotowe do druku z lokalnej bazy danych.

        Szuka zamowien w statusie 'pobrano' (nowe z Allegro Events API),
        ktore nie zostaly jeszcze wydrukowane.
        """
        from .db import get_session
        from .models import Order, OrderStatusLog
        from sqlalchemy import desc

        orders = []
        try:
            with get_session() as db:
                # Pobierz zamowienia z ostatnich 7 dni
                week_ago = int((datetime.now() - timedelta(days=7)).timestamp())

                recent_orders = (
                    db.query(Order)
                    .filter(Order.date_add >= week_ago)
                    .all()
                )

                for order in recent_orders:
                    # Sprawdz aktualny status
                    latest = (
                        db.query(OrderStatusLog)
                        .filter(OrderStatusLog.order_id == order.order_id)
                        .order_by(desc(OrderStatusLog.timestamp))
                        .first()
                    )
                    current_status = latest.status if latest else "pobrano"

                    # Interesuja nas tylko zamowienia w statusie 'pobrano' lub 'blad_druku' (retry)
                    if current_status == "blad_druku":
                        # Policz ile razy bylo blad_druku - max 3 retry
                        from sqlalchemy import func as sa_func
                        error_count = (
                            db.query(sa_func.count(OrderStatusLog.id))
                            .filter(
                                OrderStatusLog.order_id == order.order_id,
                                OrderStatusLog.status == "blad_druku",
                            )
                            .scalar()
                        ) or 0
                        if error_count >= 3:
                            continue
                    elif current_status != "pobrano":
                        continue

                    # Pobierz produkty
                    products_list = []
                    for op in order.products:
                        products_list.append({
                            "name": op.name or "",
                            "quantity": op.quantity or 1,
                            "price_brutto": str(op.price_brutto) if op.price_brutto else "0",
                            "auction_id": op.auction_id or "",
                            "sku": op.sku or "",
                            "ean": op.ean or "",
                            "attributes": op.attributes or "",
                        })

                    orders.append({
                        "order_id": order.order_id,
                        "external_order_id": order.external_order_id or "",
                        "shop_order_id": order.shop_order_id,
                        "delivery_fullname": order.delivery_fullname or "",
                        "email": order.email or "",
                        "phone": order.phone or "",
                        "user_login": order.user_login or "",
                        "order_source": order.platform or "allegro",
                        "order_source_id": order.order_source_id,
                        "order_status_id": order.order_status_id,
                        "confirmed": order.confirmed,
                        "date_add": order.date_add,
                        "date_confirmed": order.date_confirmed,
                        "date_in_status": order.date_in_status,
                        "delivery_method": order.delivery_method or "",
                        "delivery_method_id": order.delivery_method_id,
                        "delivery_price": float(order.delivery_price) if order.delivery_price else 0,
                        "delivery_company": order.delivery_company or "",
                        "delivery_address": order.delivery_address or "",
                        "delivery_city": order.delivery_city or "",
                        "delivery_postcode": order.delivery_postcode or "",
                        "delivery_country": order.delivery_country or "",
                        "delivery_country_code": order.delivery_country_code or "",
                        "delivery_point_id": order.delivery_point_id or "",
                        "delivery_point_name": order.delivery_point_name or "",
                        "delivery_point_address": order.delivery_point_address or "",
                        "delivery_point_postcode": order.delivery_point_postcode or "",
                        "delivery_point_city": order.delivery_point_city or "",
                        "invoice_fullname": order.invoice_fullname or "",
                        "invoice_company": order.invoice_company or "",
                        "invoice_nip": order.invoice_nip or "",
                        "invoice_address": order.invoice_address or "",
                        "invoice_city": order.invoice_city or "",
                        "invoice_postcode": order.invoice_postcode or "",
                        "invoice_country": order.invoice_country or "",
                        "want_invoice": order.want_invoice or "0",
                        "currency": order.currency or "PLN",
                        "payment_method": order.payment_method or "",
                        "payment_method_cod": order.payment_method_cod or "0",
                        "payment_done": float(order.payment_done) if order.payment_done else 0,
                        "user_comments": order.user_comments or "",
                        "admin_comments": order.admin_comments or "",
                        "courier_code": order.courier_code or "",
                        "delivery_package_module": order.delivery_package_module or "",
                        "delivery_package_nr": order.delivery_package_nr or "",
                        "products": products_list,
                    })

                self.logger.debug("Znaleziono %d zamowien do druku", len(orders))
        except Exception as exc:
            self.logger.error("Blad pobierania zamowien z bazy: %s", exc)
            raise ApiError(str(exc)) from exc

        return orders

    def get_order_packages(self, order_id: str) -> List[Dict[str, Any]]:
        """Pobierz przesylki dla zamowienia z Allegro Shipment Management API.

        Jezeli przesylka SM nie istnieje, tworzy ja automatycznie.
        checkout-forms/shipments zwraca ID base64 (nieprzydatne do etykiet).
        Shipment-management wymaga UUID - zapisujemy go w agent_state.
        """
        # Wyciagnij checkout_form_id z order_id (format: allegro_{uuid})
        checkout_form_id = order_id
        if order_id.startswith("allegro_"):
            checkout_form_id = order_id[len("allegro_"):]

        # 1. Sprawdz zapisany shipment_management UUID
        stored_sm_id = self._load_state_value(f"sm_shipment:{order_id}")
        if stored_sm_id:
            try:
                details = get_shipment_details(stored_sm_id)
                carrier = details.get("carrier", "")
                waybill = ""
                for pkg in details.get("packages", []):
                    waybill = pkg.get("waybill", "")
                    if waybill:
                        break
                self.logger.info(
                    "Uzyto zapisany shipment_management_id=%s dla %s",
                    stored_sm_id, order_id,
                )
                return [{
                    "shipment_id": stored_sm_id,
                    "waybill": waybill,
                    "carrier_id": carrier,
                    "courier_code": carrier,
                    "courier_package_nr": waybill,
                }]
            except Exception as exc:
                self.logger.warning(
                    "Blad pobierania przesylki SM %s: %s. Usuwam mapping.",
                    stored_sm_id, exc,
                )
                self._save_state_value(f"sm_shipment:{order_id}", None)

        # 2. Brak SM UUID - utworz nowa przesylke przez Shipment Management
        #    (checkout-forms moze miec przesylki, ale ich ID base64
        #     nie nadaja sie do pobierania etykiet)
            self.logger.info(
                "Brak zapisanego shipment_management_id dla %s - tworze nowa przesylke",
                order_id,
            )
        return self._create_allegro_shipment(order_id, checkout_form_id)

    def _create_allegro_shipment(
        self, order_id: str, checkout_form_id: str,
    ) -> List[Dict[str, Any]]:
        """Utworz przesylke w Allegro Shipment Management i zwroc dane."""
        return self._shipment_creator().create(
            order_id,
            checkout_form_id,
            self.last_order_data,
        )

    def _shipment_creator(self) -> PrintShipmentCreator:
        from .settings_store import settings_store

        return PrintShipmentCreator(
            logger=self.logger,
            settings_store=settings_store,
            fetch_order_detail=fetch_allegro_order_detail,
            resolve_delivery_service_id=self._resolve_delivery_service_id,
            resolve_carrier_id=self._resolve_carrier_id,
            create_shipment=create_shipment,
            wait_for_shipment_creation=wait_for_shipment_creation,
            get_shipment_details=get_shipment_details,
            add_shipment_tracking=add_shipment_tracking,
            update_fulfillment_status=update_fulfillment_status,
            save_state_value=self._save_state_value,
        )

    def _resolve_delivery_service_id(self, delivery_method: str) -> Optional[str]:
        """Mapuj nazwe metody dostawy Allegro na deliveryMethodId.

        Preferuje uslugi Allegro Standard (SMART, bez credentialsId) nad
        umowami wlasnymi, aby przesylki tworzone byly w ramach SMART
        zamiast ze srodkow wlasnego konta przewoznika.
        """
        if not delivery_method:
            return None

        try:
            services = get_delivery_services()
        except Exception as exc:
            self.logger.error("Blad pobierania delivery services: %s", exc)
            return None
        return resolve_delivery_service_id(delivery_method, services, self.logger)

    def _resolve_carrier_id(self, delivery_method: str) -> Optional[str]:
        """Mapuj nazwe metody dostawy na carrier_id Allegro."""
        return resolve_carrier_id(delivery_method)

    def _label_service(self) -> PrintLabelService:
        return PrintLabelService(
            logger=self.logger,
            get_shipment_label=get_shipment_label,
            cancel_shipment=cancel_shipment,
            create_shipment=lambda order_id, checkout_form_id: self._create_allegro_shipment(
                order_id,
                checkout_form_id,
            ),
            fetch_label=lambda courier_code, package_id: self.get_label(
                courier_code,
                package_id,
            ),
            recreate_shipment_and_get_label=(
                lambda order_id, old_shipment_id, courier_code, package_ids, tracking_numbers:
                self._recreate_shipment_and_get_label(
                    order_id,
                    old_shipment_id,
                    courier_code,
                    package_ids,
                    tracking_numbers,
                )
            ),
            retry=self._retry,
            errors_total=PRINT_LABEL_ERRORS_TOTAL,
        )

    def _collect_order_labels(
        self,
        order_id: str,
        packages: List[Dict[str, Any]],
    ) -> CollectedLabels:
        return self._label_service().collect_order_labels(order_id, packages)

    def _recreate_shipment_and_get_label(
        self,
        order_id: str,
        old_shipment_id: str,
        courier_code: str,
        package_ids: List[str],
        tracking_numbers: List[str],
    ) -> Tuple[str, str]:
        """Anuluj wygasla przesylke, stworz nowa i pobierz etykiete.

        Aktualizuje package_ids i tracking_numbers in-place.

        Returns:
            Tuple (base64_label_data, extension) lub ("", "") przy bledzie.
        """
        return self._label_service().recreate_shipment_and_get_label(
            order_id,
            old_shipment_id,
            courier_code,
            package_ids,
            tracking_numbers,
        )

    def get_label(self, courier_code: str, package_id: str) -> Tuple[str, str]:
        """Pobierz etykiete przesylki z Allegro Shipment Management API.

        Args:
            courier_code: Nieuzywane (kompatybilnosc wsteczna).
            package_id: ID przesylki (shipment_id) z Allegro.

        Returns:
            Tuple (base64_label_data, extension).

        Raises:
            ShipmentExpiredError: Przesylka wygasla (403) - wymaga recreate.
        """
        return self._label_service().get_label(courier_code, package_id)

    def print_label(self, base64_data: str, extension: str, order_id: str) -> None:
        try:
            self.printer.print_label_base64(base64_data, extension)
            self.logger.info("Label printed")
            PRINT_LABELS_TOTAL.inc()
        except PrintCommandError as exc:
            PRINT_LABEL_ERRORS_TOTAL.labels(stage="print").inc()
            raise PrintError(str(exc)) from exc
        except PrintError:
            raise
        except Exception as exc:
            self.logger.error("Błąd drukowania: %s", exc)
            PRINT_LABEL_ERRORS_TOTAL.labels(stage="print").inc()
            raise PrintError(str(exc)) from exc

    def print_test_page(self) -> bool:
        try:
            self.printer.print_text("=== TEST PRINT ===\n")
            self.logger.info("Testowa strona została wysłana do drukarki.")
            return True
        except Exception as exc:
            self.logger.error("Błąd testowego druku: %s", exc)
            return False

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

    def _report_service(self) -> PrintAgentReportService:
        return PrintAgentReportService(
            logger=self.logger,
            config_provider=lambda: self.config,
            send_report=send_report,
            summary_provider=self._get_period_summary,
            get_last_weekly_report=lambda: getattr(self, "_last_weekly_report", None),
            set_last_weekly_report=lambda value: setattr(self, "_last_weekly_report", value),
            get_last_monthly_report_month=lambda: getattr(
                self,
                "_last_monthly_report_month",
                None,
            ),
            set_last_monthly_report_month=lambda value: setattr(
                self,
                "_last_monthly_report_month",
                value,
            ),
        )

    def _send_periodic_reports(self) -> None:
        """Wysyła raporty tygodniowe i miesięczne przez Messenger.
        
        Format raportu:
        - Tygodniowy: "W tym tygodniu sprzedałaś [ilość] produktów za [suma] zł co dało [zysk] zł zysku"
        - Miesięczny: "W miesiącu [nazwa] sprzedałaś [ilość] produktów za [suma] zł co dało [zysk] zł zysku"
        """
        self._report_service().send_periodic_reports()
    
    def _get_period_summary(self, days: int, end_date: datetime = None, include_fixed_costs: bool = False) -> dict:
        """Pobiera podsumowanie sprzedazy za okres z obliczeniem realnego zysku.
        
        Args:
            days: Liczba dni wstecz od end_date
            end_date: Data koncowa (domyslnie teraz)
            include_fixed_costs: Czy odejmowac koszty stale (dla raportow miesiecznych)
            
        Returns:
            Dict z kluczami: products_sold, total_revenue, real_profit, fixed_costs (opcjonalnie)
        """
        return self._report_service().get_period_summary(
            days,
            end_date=end_date,
            include_fixed_costs=include_fixed_costs,
        )

    def _process_queue(self, queue: List[Dict[str, Any]], printed: Dict[str, Any]) -> List[Dict[str, Any]]:
        processor = PrintQueueProcessor(
            logger=self.logger,
            is_quiet_time=self.is_quiet_time,
            save_queue=self.save_queue,
            mark_as_printed=self.mark_as_printed,
            notify_messenger=self._notify_messenger,
            retry=self._retry,
            print_label=self.print_label,
            consume_order_stock=consume_order_stock,
            print_error_type=PrintError,
            errors_total=PRINT_LABEL_ERRORS_TOTAL,
            now=lambda: datetime.now(),
        )
        return processor.process(queue, printed)

    def _order_processor(self) -> PrintOrderProcessor:
        return PrintOrderProcessor(
            logger=self.logger,
            set_last_order_data=lambda data: setattr(self, "last_order_data", data),
            retry=self._retry,
            get_order_packages=self.get_order_packages,
            collect_order_labels=self._collect_order_labels,
            is_quiet_time=self.is_quiet_time,
            save_queue=self.save_queue,
            print_label=self.print_label,
            mark_as_printed=self.mark_as_printed,
            notify_messenger=self._notify_messenger,
            consume_order_stock=consume_order_stock,
            should_send_error_notification=self._should_send_error_notification,
            send_label_error_notification=self._send_label_error_notification,
            increment_error_notification=self.notifier.increment_error_notification,
            wait=self._stop_event.wait,
            errors_total=PRINT_LABEL_ERRORS_TOTAL,
            print_error_type=PrintError,
            now=lambda: datetime.now(),
        )

    def _check_allegro_discussions(self, access_token: str) -> None:
        """Sprawdza dyskusje Allegro - deleguje do AllegroSyncService."""
        service = AllegroSyncService(
            db_file=self.config.db_file,
            settings=self.settings,
            save_state_callback=self._save_state_value
        )
        service.check_discussions(access_token)

    def _check_allegro_messages(self, access_token: str) -> None:
        """Sprawdza wiadomosci Allegro - deleguje do AllegroSyncService."""
        service = AllegroSyncService(
            db_file=self.config.db_file,
            settings=self.settings,
            save_state_callback=self._save_state_value
        )
        service.check_messages(access_token)

    def _agent_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._run_print_iteration()
            except Exception as exc:
                self.logger.error("[BLAD ITERACJI GLOWNEJ] %s", exc, exc_info=True)
                PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
            self._stop_event.wait(self.config.poll_interval)

    def _run_print_iteration(self) -> None:
        """Pojedyncza iteracja petli drukowania - izolowana od bledow."""
        loop_start = datetime.now()
        self._write_heartbeat()

        self.clean_old_printed_orders()
        printed_entries = self.load_printed_orders()
        printed = {entry["order_id"]: entry["printed_at"] for entry in printed_entries}
        queue = self.load_queue()

        queue = self._restore_in_progress(queue)

        queue = self._process_queue(queue, printed)
        self.save_queue(queue)

        try:
            try:
                orders = self._retry(
                    self.get_orders,
                    stage="orders",
                    retry_exceptions=(ApiError,),
                )
            except ApiError as exc:
                self.logger.error("Blad pobierania zamowien: %s", exc)
                PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
                orders = []
            order_processor = self._order_processor()
            for order in orders:
                order_processor.process(order, queue, printed)
        except Exception as exc:
            self.logger.error("[BLAD PETLI ZAMOWIEN] %s", exc)
            PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()

        self.save_queue(queue)
        duration = (datetime.now() - loop_start).total_seconds()
        PRINT_AGENT_ITERATION_SECONDS.observe(duration)
        self._write_heartbeat()

    def start_agent_thread(self) -> bool:
        if self._agent_thread and self._agent_thread.is_alive():
            return False

        if not self._heartbeat_lock.acquire():
            self.logger.info("Print agent already running, skipping startup")
            return False

        self._lock_handle = self._heartbeat_lock.lock_handle
        self._stop_event = self._thread_runtime.stop_event
        if not self._thread_runtime.start(
            self._agent_loop,
            already_running_message="Print agent already running",
            started_message="Print agent thread started",
        ):
            self._heartbeat_lock.release()
            self._lock_handle = None
            return False
        self._agent_thread = self._thread_runtime.thread

        # Uruchom niezalezne workery
        self._workers = [
            TrackingWorker(self),
            MessagingWorker(self),
            ReportWorker(self),
        ]
        for worker in self._workers:
            worker.start()
            self.logger.info("Uruchomiono worker: %s", worker.name)

        return True

    def _notify_messenger(self, data: Dict[str, Any], print_success: bool) -> None:
        """Call ``send_messenger_message`` while tolerating simplified monkeypatches."""
        notify_messenger(self.send_messenger_message, data, print_success)

    def stop_agent_thread(self) -> None:
        # Zatrzymaj workery
        for worker in self._workers:
            worker.stop()
            self.logger.info("Zatrzymano worker: %s", worker.name)
        self._workers = []

        self._thread_runtime.stop(
            stopping_message="Stopping print agent thread...",
            stopped_message="Print agent thread stopped",
        )
        self._agent_thread = None
        self._heartbeat_lock.release()
        self._lock_handle = None
        token_refresher.stop()


# Instantiate default agent used throughout the application.
agent = LabelAgent(AgentConfig.from_settings(settings), settings)
logger = agent.logger


def __getattr__(name: str) -> Any:
    if hasattr(agent, name):
        return getattr(agent, name)
    lower_name = name.lower()
    if hasattr(agent.config, lower_name):
        return getattr(agent.config, lower_name)
    raise AttributeError(name)


__all__ = [
    "AgentConfig",
    "LabelAgent",
    "ConfigError",
    "ApiError",
    "PrintError",
    "agent",
    "logger",
    "calculate_cod_amount",
    "parse_product_info",
    "parse_time_str",
    "PRINT_QUEUE_OLDEST_AGE_SECONDS",
    "PRINT_QUEUE_SIZE",
    "shorten_product_name",
]
