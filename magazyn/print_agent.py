from __future__ import annotations

import base64
import logging
import os
import threading
import time

# fcntl is Unix-only, provide fallback for Windows
try:
    import fcntl
except ImportError:
    fcntl = None
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
    is_cod_order,
    parse_time_str,
)
from .services.print_agent_delivery import resolve_delivery_service_id
from .services.print_agent_notifications import PrintAgentNotifier, notify_messenger
from .services.print_agent_order_data import apply_package_tracking, build_last_order_data
from .services.print_agent_queue import PrintQueueProcessor
from .services.print_agent_status import set_print_error_status
from .services.print_agent_storage import PrintAgentStorage, SuccessMarker
from .services.print_agent_shipments import (
    build_additional_services,
    build_cod_payload,
    build_packages,
    build_receiver,
    build_sender,
    resolve_carrier_id,
    shorten_product_name,
)
from .services.printing import CupsPrinter, PrintCommandError
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


class ApiError(Exception):
    """Raised when an API call fails."""


class PrintError(Exception):
    """Raised when sending data to the printer fails."""


class ShipmentExpiredError(ApiError):
    """Przesylka wygasla/anulowana - wymaga ponownego utworzenia."""

    def __init__(self, shipment_id: str, message: str = ""):
        self.shipment_id = shipment_id
        super().__init__(message or f"Przesylka {shipment_id} wygasla (403)")


T = TypeVar("T")


# Uzywamy short_preview z modulu utils


class LabelAgent:
    """Encapsulates the state and behaviour of the label printing agent."""

    def __init__(self, config: AgentConfig, settings_obj: Any):
        self.config = config
        self.settings = settings_obj
        self.logger = logging.getLogger(__name__)
        self.last_order_data: Dict[str, Any] = {}
        self._agent_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._rate_limit_lock = threading.Lock()
        self._lock_handle = None
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
        return f"{self.config.lock_file}.heartbeat"

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
        try:
            with open(self._heartbeat_path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _write_heartbeat(self) -> None:
        try:
            with open(self._heartbeat_path, "w", encoding="utf-8") as handle:
                handle.write(datetime.now().isoformat())
        except OSError as exc:  # pragma: no cover - best effort logging only
            self.logger.debug("Nie można zapisać heartbeat: %s", exc)

    def _clear_heartbeat(self) -> None:
        try:
            os.remove(self._heartbeat_path)
        except OSError:
            pass

    def _cleanup_orphaned_lock(self) -> None:
        heartbeat = self._read_heartbeat()
        if heartbeat is None:
            return
        grace = max(1, self.config.poll_interval)
        max_age = timedelta(seconds=grace * 4)
        if datetime.now() - heartbeat <= max_age:
            return

        try:
            with open(self.config.lock_file, "a+", encoding="utf-8") as handle:
                try:
                    if fcntl:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # On Windows without fcntl, skip lock check
                except OSError:
                    return
        except OSError:
            self._clear_heartbeat()
            return

        try:
            os.remove(self.config.lock_file)
        except OSError:
            pass
        else:
            self.logger.warning("Wyczyszczono porzuconą blokadę agenta drukowania")
        self._clear_heartbeat()

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
        order_data = self.last_order_data
        if not order_data or order_data.get("order_id") != order_id:
            self.logger.error("Brak danych zamowienia %s do utworzenia przesylki", order_id)
            return []

        # Pobierz delivery_method_id (UUID) bezposrednio z Allegro API
        # DB model przechowuje wewnetrzny FK (Integer), wiec musimy pobrac UUID z API
        # WAZNE: delivery.method.id z checkout-form to ID uslugi Allegro Standard (SMART).
        # Jesli sprzedawca ma umowe wlasna z InPost, delivery-services zwraca dwa
        # wpisy z ROZNYMI deliveryMethodId - Allegro Standard i umowa wlasna.
        # Musimy uzywac Allegro Standard aby przesylka szla w ramach SMART.
        delivery_method_id = None
        delivery_method = order_data.get("delivery_method", "") or order_data.get("shipping", "")
        try:
            allegro_detail = fetch_allegro_order_detail(checkout_form_id)
            allegro_delivery = (allegro_detail.get("delivery") or {}).get("method") or {}
            delivery_method_id = allegro_delivery.get("id")
            if not delivery_method:
                delivery_method = allegro_delivery.get("name", "")
            self.logger.info(
                "Pobrano delivery_method_id=%s z checkout-form (Allegro Standard/SMART) "
                "dla zamowienia %s (metoda: %s)",
                delivery_method_id, order_id, delivery_method,
            )
        except Exception as exc:
            self.logger.warning(
                "Nie mozna pobrac delivery.method.id z Allegro API dla %s: %s",
                checkout_form_id, exc,
            )

        if not delivery_method_id:
            # Fallback: sprobuj znalezc po nazwie w delivery-services
            # UWAGA: preferujemy uslugi Allegro Standard (SMART) nad umowami wlasnymi
            self.logger.warning(
                "Uzyto fallback _resolve_delivery_service_id dla zamowienia %s "
                "(delivery_method='%s') - checkout form nie zwrocil delivery.method.id",
                order_id, delivery_method,
            )
            delivery_method_id = self._resolve_delivery_service_id(delivery_method)

        if not delivery_method_id:
            self.logger.error(
                "Nie mozna ustalic delivery_method_id dla metody '%s' (zamowienie %s)",
                delivery_method, order_id,
            )
            return []

        from .settings_store import settings_store
        sender = build_sender(settings_store)
        receiver = build_receiver(order_data)
        products = order_data.get("products", [])
        packages, reference_number = build_packages(products)
        carrier_id = self._resolve_carrier_id(delivery_method)
        additional_services = build_additional_services(carrier_id)

        try:
            cod_payload = build_cod_payload(order_data)

            # 1. Wyslij komende tworzenia (async)
            cmd_result = create_shipment(
                delivery_method_id=delivery_method_id,
                sender=sender,
                receiver=receiver,
                packages=packages,
                cash_on_delivery=cod_payload,
                reference_number=reference_number,
                additional_services=additional_services,
            )

            command_id = cmd_result.get("commandId")
            if not command_id:
                self.logger.error("Brak commandId w odpowiedzi create_shipment")
                return []

            # 2. Poczekaj na wynik (status SUCCESS)
            creation_result = wait_for_shipment_creation(command_id)
            shipment_id = creation_result.get("shipmentId")

            if not shipment_id:
                self.logger.error("Brak shipmentId po utworzeniu (commandId=%s)", command_id)
                return []

            # 3. Pobierz szczegoly przesylki (waybill itp.)
            waybill = ""
            try:
                details = get_shipment_details(shipment_id)
                for pkg in details.get("packages", []):
                    waybill = pkg.get("waybill", "")
                    if waybill:
                        break
            except Exception as det_exc:
                self.logger.warning(
                    "Nie mozna pobrac szczegolow przesylki %s: %s",
                    shipment_id, det_exc,
                )

            # Dodaj tracking do zamowienia w Allegro
            if waybill and carrier_id:
                try:
                    add_shipment_tracking(
                        checkout_form_id,
                        carrier_id=carrier_id,
                        waybill=waybill,
                    )
                except Exception as track_exc:
                    self.logger.warning(
                        "Nie mozna dodac trackingu %s do zamowienia %s: %s",
                        waybill, order_id, track_exc,
                    )

            # Zmien status fulfillment na PROCESSING
            try:
                update_fulfillment_status(checkout_form_id, "PROCESSING")
            except Exception as ful_exc:
                self.logger.warning(
                    "Nie mozna zmienic statusu fulfillment dla %s: %s",
                    order_id, ful_exc,
                )

            # Zapisz UUID shipment-management w agent_state
            self._save_state_value(f"sm_shipment:{order_id}", shipment_id)

            self.logger.info(
                "Utworzono przesylke %s (waybill: %s) dla zamowienia %s",
                shipment_id, waybill, order_id,
            )

            return [{
                "shipment_id": shipment_id,
                "waybill": waybill,
                "carrier_id": carrier_id or "",
                "courier_code": carrier_id or "",
                "courier_package_nr": waybill,
            }]

        except Exception as exc:
            self.logger.error(
                "Blad tworzenia przesylki dla zamowienia %s: %s", order_id, exc,
            )
            # Loguj body odpowiedzi z API przy HTTPError (zawiera szczegoly walidacji)
            resp = getattr(exc, "response", None)
            if resp is not None:
                try:
                    error_body = resp.json()
                    errors = error_body.get("errors", [])
                    for err in errors:
                        self.logger.error(
                            "  SM API error: path=%s code=%s message=%s userMessage=%s",
                            err.get("path"), err.get("code"),
                            err.get("message"), err.get("userMessage"),
                        )
                    if not errors:
                        self.logger.error("  SM API response body: %s", resp.text[:500])
                except Exception:
                    self.logger.error("  SM API response body: %s", resp.text[:500])
            return []

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
        checkout_form_id = order_id
        if order_id.startswith("allegro_"):
            checkout_form_id = order_id[len("allegro_"):]

        # 1. Anuluj stara przesylke
        try:
            cancel_shipment(old_shipment_id)
            self.logger.info("Anulowano wygasla przesylke %s", old_shipment_id)
        except Exception as exc:
            self.logger.warning(
                "Nie mozna anulowac przesylki %s (moze juz anulowana): %s",
                old_shipment_id, exc,
            )

        # Usun stary shipment_id z listy
        if old_shipment_id in package_ids:
            package_ids.remove(old_shipment_id)

        # 2. Stworz nowa przesylke
        try:
            new_packages = self._create_allegro_shipment(order_id, checkout_form_id)
        except Exception as exc:
            self.logger.error(
                "Blad tworzenia nowej przesylki dla %s: %s", order_id, exc,
            )
            return "", ""

        if not new_packages:
            self.logger.error("Nie utworzono nowej przesylki dla %s", order_id)
            return "", ""

        new_shipment_id = None
        for pkg in new_packages:
            sid = pkg.get("shipment_id")
            waybill = pkg.get("waybill") or pkg.get("courier_package_nr")
            if sid:
                new_shipment_id = str(sid)
                package_ids.append(new_shipment_id)
            if waybill:
                tracking_numbers.append(str(waybill))

        if not new_shipment_id:
            self.logger.error("Brak shipment_id w nowej przesylce dla %s", order_id)
            return "", ""

        self.logger.info(
            "Utworzono nowa przesylke %s (stara: %s) dla zamowienia %s",
            new_shipment_id, old_shipment_id, order_id,
        )

        # 3. Pobierz etykiete z nowej przesylki
        try:
            label_data, ext = self.get_label(courier_code, new_shipment_id)
            return label_data, ext
        except Exception as exc:
            self.logger.error(
                "Blad pobierania etykiety z nowej przesylki %s: %s",
                new_shipment_id, exc,
            )
            return "", ""

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
        if not package_id:
            raise ApiError("Brak ID przesylki do pobrania etykiety")

        def _fetch_label_attempt(logical_attempt: int) -> Tuple[str, str]:
            self.logger.info(
                "Proba pobrania etykiety: shipment_id=%s courier_code=%s attempt=%d",
                package_id,
                courier_code or "",
                logical_attempt,
            )
            label_bytes = get_shipment_label([package_id], page_size="A6", cut_line=False)
            label_b64 = base64.b64encode(label_bytes).decode("ascii")
            self.logger.info(
                "Pobrano etykiete: shipment_id=%s courier_code=%s attempt=%d bytes=%d",
                package_id,
                courier_code or "",
                logical_attempt,
                len(label_bytes),
            )
            return label_b64, "pdf"

        try:
            return _fetch_label_attempt(1)
        except RuntimeError as exc:
            # Etykieta nie gotowa - sprobuj ponownie po chwili
            self.logger.warning("Etykieta nie gotowa dla %s: %s", package_id, exc)
            time.sleep(3)
            try:
                return _fetch_label_attempt(2)
            except Exception as retry_exc:
                raise ApiError(f"Etykieta niedostepna: {retry_exc}") from retry_exc
        except Exception as exc:
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None,
            )
            if status_code == 403:
                raise ShipmentExpiredError(package_id, str(exc)) from exc
            raise ApiError(f"Blad pobierania etykiety: {exc}") from exc

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
        try:
            from .services.order_status import add_order_status
            from .db import get_session
            from .models import Order, OrderStatusLog
            from .allegro_api.tracking import fetch_parcel_tracking
            from .settings_store import settings_store
            from sqlalchemy import desc

            access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
            if not access_token:
                self.logger.debug("Brak tokenu Allegro - pomijam sprawdzanie trackingu")
                return

            with get_session() as db:
                from datetime import datetime, timedelta
                week_ago = int((datetime.now() - timedelta(days=7)).timestamp())

                orders_to_check = (
                    db.query(Order)
                    .filter(Order.date_add >= week_ago)
                    .all()
                )

                if not orders_to_check:
                    return

                # Zbierz zamowienia z waybill pogrupowane po carrier
                carrier_waybills: Dict[str, List[Tuple[Order, str, str]]] = {}
                for order in orders_to_check:
                    latest_status = (
                        db.query(OrderStatusLog)
                        .filter(OrderStatusLog.order_id == order.order_id)
                        .order_by(desc(OrderStatusLog.timestamp))
                        .first()
                    )
                    current_status = latest_status.status if latest_status else "pobrano"

                    if current_status in ("dostarczono", "zwrot", "anulowano", "problem_z_dostawa"):
                        continue

                    waybill = order.delivery_package_nr
                    if not waybill:
                        continue

                    carrier_id = self._resolve_carrier_id(
                        order.delivery_method or order.delivery_package_module or ""
                    ) or "OTHER"

                    carrier_waybills.setdefault(carrier_id, []).append(
                        (order, waybill, current_status)
                    )

                self.logger.debug(
                    "Sprawdzam tracking dla %d zamowien (%d przewoznikow)",
                    sum(len(v) for v in carrier_waybills.values()),
                    len(carrier_waybills),
                )

                # Odpytaj Allegro Tracking API per carrier (max 20 waybilli per request)
                for carrier_id, order_items in carrier_waybills.items():
                    waybill_to_order = {item[1]: (item[0], item[2]) for item in order_items}
                    waybill_list = list(waybill_to_order.keys())

                    # Podziel na batche po 20
                    for i in range(0, len(waybill_list), 20):
                        batch = waybill_list[i:i + 20]
                        try:
                            tracking_data = fetch_parcel_tracking(
                                access_token, carrier_id, batch
                            )
                        except Exception as exc:
                            self.logger.warning(
                                "Blad pobierania trackingu %s: %s", carrier_id, exc
                            )
                            continue

                        for wb_data in tracking_data.get("waybills", []):
                            waybill = wb_data.get("waybill", "")
                            if waybill not in waybill_to_order:
                                continue

                            order_obj, current_status = waybill_to_order[waybill]
                            events = wb_data.get("events", [])
                            if not events:
                                continue

                            # Najnowszy event (pierwszy na liscie)
                            latest_event = events[0]
                            event_type = latest_event.get("type", "")
                            new_status = self.ALLEGRO_TRACKING_STATUS_MAP.get(event_type)

                            if not new_status or new_status == current_status:
                                continue

                            self.logger.info(
                                "Zmiana statusu zamowienia %s: %s -> %s (event: %s)",
                                order_obj.order_id, current_status, new_status, event_type,
                            )

                            try:
                                add_order_status(
                                    db, order_obj.order_id, new_status,
                                    tracking_number=waybill,
                                    courier_code=carrier_id,
                                    notes=f"Auto-update z Allegro Tracking ({event_type})",
                                )

                                # Gdy tracking potwierdzi nadanie, zsynchronizuj fulfillment Allegro.
                                if new_status == "wyslano" and order_obj.external_order_id:
                                    try:
                                        update_fulfillment_status(order_obj.external_order_id, "SENT")
                                    except Exception as ful_exc:
                                        self.logger.warning(
                                            "Nie mozna ustawic fulfillment SENT dla %s: %s",
                                            order_obj.order_id,
                                            ful_exc,
                                        )

                                db.commit()
                            except Exception as status_exc:
                                self.logger.warning(
                                    "Blad aktualizacji statusu %s: %s",
                                    order_obj.order_id, status_exc,
                                )
                                db.rollback()

        except Exception as exc:
            self.logger.warning("Blad sprawdzania statusow przesylek: %s", exc)

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

    def _send_periodic_reports(self) -> None:
        """Wysyła raporty tygodniowe i miesięczne przez Messenger.
        
        Format raportu:
        - Tygodniowy: "W tym tygodniu sprzedałaś [ilość] produktów za [suma] zł co dało [zysk] zł zysku"
        - Miesięczny: "W miesiącu [nazwa] sprzedałaś [ilość] produktów za [suma] zł co dało [zysk] zł zysku"
        """
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # Wysylka raportu tygodniowego - co 7 dni
        if self.config.enable_weekly_reports and (
            not hasattr(self, "_last_weekly_report")
            or not self._last_weekly_report
            or now - self._last_weekly_report >= timedelta(days=7)
        ):
            summary = self._get_period_summary(days=7)
            if summary:
                message = (
                    f"W tym tygodniu sprzedałaś {summary['products_sold']} produktów "
                    f"za {summary['total_revenue']:.2f} zł co dało {summary['real_profit']:.2f} zł zysku"
                )
                send_report("Raport tygodniowy", [message])
                self._last_weekly_report = now
        
        # Wysylka raportu miesiecznego - 1. dnia miesiaca za poprzedni miesiac
        if self.config.enable_monthly_reports:
            # Sprawdz czy jest 1. dzien miesiaca i czy raport za poprzedni miesiac juz wyslany
            is_first_day = now.day == 1
            last_report_month = getattr(self, "_last_monthly_report_month", None)
            
            if is_first_day and last_report_month != (now.year, now.month):
                # Pobierz dane za poprzedni miesiac
                prev_month_end = (now.replace(day=1) - timedelta(days=1))
                prev_month_start = prev_month_end.replace(day=1)
                days_in_prev_month = (prev_month_end - prev_month_start).days + 1
                
                MONTH_NAMES = ['Styczen', 'Luty', 'Marzec', 'Kwiecien', 'Maj', 'Czerwiec',
                               'Lipiec', 'Sierpien', 'Wrzesien', 'Pazdziernik', 'Listopad', 'Grudzien']
                month_name = MONTH_NAMES[prev_month_end.month - 1]
                
                summary = self._get_period_summary(days=days_in_prev_month, end_date=prev_month_end, include_fixed_costs=True)
                if summary:
                    # Dodaj informacje o kosztach stalych jesli sa
                    fixed_info = ""
                    if summary.get('fixed_costs', 0) > 0:
                        fixed_info = f" (po odliczeniu {summary['fixed_costs']:.0f} zł kosztów stałych)"
                    message = (
                        f"W miesiącu {month_name} sprzedałaś {summary['products_sold']} produktów "
                        f"za {summary['total_revenue']:.2f} zł co dało {summary['real_profit']:.2f} zł zysku{fixed_info}"
                    )
                    send_report("Raport miesieczny", [message])
                    self._last_monthly_report_month = (now.year, now.month)
    
    def _get_period_summary(self, days: int, end_date: datetime = None, include_fixed_costs: bool = False) -> dict:
        """Pobiera podsumowanie sprzedazy za okres z obliczeniem realnego zysku.
        
        Args:
            days: Liczba dni wstecz od end_date
            end_date: Data koncowa (domyslnie teraz)
            include_fixed_costs: Czy odejmowac koszty stale (dla raportow miesiecznych)
            
        Returns:
            Dict z kluczami: products_sold, total_revenue, real_profit, fixed_costs (opcjonalnie)
        """
        from datetime import datetime, timedelta
        
        if end_date is None:
            end_date = datetime.now()
        
        start_date = end_date - timedelta(days=days)
        start_ts = int(start_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        end_ts = int(end_date.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
        
        try:
            from .db import get_session
            from .domain.financial import FinancialCalculator
            from .settings_store import settings_store
            
            access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
            
            with get_session() as db:
                calculator = FinancialCalculator(db, settings_store)
                summary = calculator.get_period_summary(
                    start_ts, 
                    end_ts,
                    include_fixed_costs=include_fixed_costs,
                    access_token=access_token
                )
                
                result = {
                    "products_sold": summary.products_sold,
                    "total_revenue": float(summary.total_revenue),
                    "real_profit": float(summary.net_profit if include_fixed_costs else summary.gross_profit),
                }
                if include_fixed_costs:
                    result["profit_before_fixed"] = float(summary.gross_profit)
                    result["fixed_costs"] = float(summary.fixed_costs)
                    result["fixed_costs_list"] = summary.fixed_costs_list
                return result
                
        except Exception as e:
            self.logger.error("Blad pobierania podsumowania sprzedazy: %s", e)
            return None

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
            for order in orders:
                order_id = str(order["order_id"])
                self.last_order_data = build_last_order_data(order)

                if order_id in printed:
                    continue

                # Sprawdź czy zamówienie jest już w kolejce oczekującej
                queued_order_ids = {item["order_id"] for item in queue}
                if order_id in queued_order_ids:
                    continue

                # Blokada druku dla nieopłaconych zamówień (nie dotyczy COD)
                payment_done = float(order.get("payment_done") or 0)
                is_cod = is_cod_order(
                    order.get("payment_method_cod", "0"),
                    order.get("payment_method", ""),
                )
                if not is_cod and payment_done <= 0:
                    self.logger.info(
                        "Pomijam %s - nieoplacone (payment_done=%.2f, cod=%s)",
                        order_id, payment_done, is_cod,
                    )
                    continue

                try:
                    packages = self._retry(
                        self.get_order_packages,
                        order_id,
                        stage="packages",
                        retry_exceptions=(ApiError,),
                    )
                except ApiError as exc:
                    self.logger.error(
                        "Błąd pobierania paczek dla %s: %s", order_id, exc
                    )
                    PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
                    if self._should_send_error_notification(order_id):
                        self._send_label_error_notification(order_id)
                    else:
                        self.notifier.increment_error_notification(order_id)
                    continue
                labels: List[Tuple[str, str]] = []
                courier_code = ""
                package_ids: List[str] = []
                tracking_numbers: List[str] = []

                for package in packages:
                    shipment_id = package.get("shipment_id")
                    code = package.get("carrier_id") or package.get("courier_code")
                    tracking_number = package.get("waybill") or package.get("courier_package_nr")
                    if code and not courier_code:
                        courier_code = code
                    if shipment_id:
                        package_ids.append(str(shipment_id))
                    if tracking_number:
                        tracking_numbers.append(str(tracking_number))
                    if not shipment_id:
                        self.logger.warning("  Brak shipment_id dla zamowienia %s", order_id)
                        continue
                    try:
                        label_data, ext = self._retry(
                            self.get_label,
                            courier_code,
                            shipment_id,
                            stage="label",
                            retry_exceptions=(ApiError,),
                        )
                    except ShipmentExpiredError:
                        self.logger.warning(
                            "Przesylka %s wygasla (403) - anuluje i tworze nowa dla %s",
                            shipment_id, order_id,
                        )
                        label_data, ext = self._recreate_shipment_and_get_label(
                            order_id, shipment_id, courier_code,
                            package_ids, tracking_numbers,
                        )
                        if not label_data:
                            PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
                            continue
                    except ApiError as exc:
                        self.logger.error(
                            "Blad pobierania etykiety %s/%s: %s",
                            courier_code,
                            shipment_id,
                            exc,
                        )
                        PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop").inc()
                        continue
                    if label_data:
                        labels.append((label_data, ext))

                apply_package_tracking(
                    self.last_order_data,
                    courier_code=courier_code,
                    package_ids=package_ids,
                    tracking_numbers=tracking_numbers,
                )

                if labels:
                    if self.is_quiet_time():
                        for label_data, ext in labels:
                            queue.append(
                                {
                                    "order_id": order_id,
                                    "label_data": label_data,
                                    "ext": ext,
                                    "last_order_data": self.last_order_data,
                                    "queued_at": datetime.now().isoformat(),
                                    "status": "queued",
                                }
                            )
                        # W quiet_hours etykieta jest w kolejce - wysyłamy info o sukcesie
                        self._notify_messenger(self.last_order_data, print_success=True)
                        self.mark_as_printed(order_id, self.last_order_data)
                        printed[order_id] = datetime.now()
                    else:
                        entries: List[Dict[str, Any]] = []
                        for label_data, ext in labels:
                            entry = {
                                "order_id": order_id,
                                "label_data": label_data,
                                "ext": ext,
                                "last_order_data": self.last_order_data,
                                "queued_at": datetime.now().isoformat(),
                                "status": "in_progress",
                            }
                            queue.append(entry)
                            entries.append(entry)
                        self.save_queue(queue)
                        print_success = True
                        try:
                            for entry in entries:
                                self._retry(
                                    self.print_label,
                                    entry["label_data"],
                                    entry.get("ext", "pdf"),
                                    entry["order_id"],
                                    stage="print",
                                    retry_exceptions=(PrintError,),
                                )
                            consume_order_stock(
                                self.last_order_data.get("products", [])
                            )
                            self.mark_as_printed(order_id, self.last_order_data)
                            printed[order_id] = datetime.now()
                            for entry in entries:
                                if entry in queue:
                                    queue.remove(entry)
                        except Exception as exc:
                            self.logger.error(
                                "Błąd drukowania zamówienia %s: %s", order_id, exc
                            )
                            print_success = False
                            set_print_error_status(
                                order_id,
                                f"Blad drukowania: {exc}",
                                self.logger,
                            )
                            for entry in entries:
                                entry["status"] = "queued"
                            self.save_queue(queue)
                            self.logger.info("Retry za 60s dla %s", order_id)
                            self._stop_event.wait(60)
                        # Zawsze wysyłaj wiadomość - z info o statusie drukowania
                        self._notify_messenger(self.last_order_data, print_success=print_success)
                else:
                    # Brak etykiety - nie mozna utworzyc przesylki w Allegro
                    self.logger.error(
                        "Brak etykiety dla zamowienia %s (Allegro nie zwrocilo danych)",
                        order_id,
                    )
                    PRINT_LABEL_ERRORS_TOTAL.labels(stage="label").inc()
                    set_print_error_status(
                        order_id,
                        "Brak etykiety - Allegro nie zwrocilo danych",
                        self.logger,
                    )
                    # Wyślij powiadomienie tylko przy 1 i 10 próbie
                    if self._should_send_error_notification(order_id):
                        self._send_label_error_notification(order_id)
                    else:
                        self.notifier.increment_error_notification(order_id)
                    self.logger.info("Retry za 60s dla %s", order_id)
                    self._stop_event.wait(60)
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

        self._cleanup_orphaned_lock()
        if self._lock_handle is None:
            try:
                self._lock_handle = open(self.config.lock_file, "w")
                if fcntl:
                    fcntl.flock(self._lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # On Windows, skip file locking
            except OSError:
                if self._lock_handle:
                    self._lock_handle.close()
                    self._lock_handle = None
                self.logger.info("Print agent already running, skipping startup")
                return False
        self._write_heartbeat()
        self._stop_event = threading.Event()
        self._agent_thread = threading.Thread(target=self._agent_loop, daemon=True)
        self._agent_thread.start()

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

        if self._agent_thread and self._agent_thread.is_alive():
            self._stop_event.set()
            self._agent_thread.join()
            self._agent_thread = None
        self._clear_heartbeat()
        if self._lock_handle:
            try:
                if fcntl:
                    fcntl.flock(self._lock_handle, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - defensive
                pass
            self._lock_handle.close()
            self._lock_handle = None
            try:
                os.remove(self.config.lock_file)
            except OSError:
                pass
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
