"""Background scheduler for automatic order synchronization."""

import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

from .services import order_events_sync, order_fulfillment_sync
from .services.order_sync_cycle import OrderSyncCallbacks, OrderSyncCycle
from .services.runtime import BackgroundThreadRuntime

logger = logging.getLogger(__name__)

_sync_thread: Optional[threading.Thread] = None
_runtime = BackgroundThreadRuntime(name="OrderSyncScheduler", logger=logger)
_stop_event = _runtime.stop_event
_last_offer_sync_date: Optional[str] = None  # YYYY-MM-DD - data ostatniego syncu ofert


def _is_http_status(exc: Exception, status_code: int) -> bool:
    return order_fulfillment_sync.is_http_status(exc, status_code)


def _sync_allegro_fulfillment(app):
    return order_fulfillment_sync.sync_allegro_fulfillment(app)


def _sync_from_allegro_events(app):
    return order_events_sync.sync_from_allegro_events(app)


def _refresh_order_profit_cache(app):
    """Odswieza zapisany realny zysk dla zamowien bez finalnych danych billingowych."""
    from sqlalchemy import or_ as db_or

    from .db import get_session
    from .domain.financial import FinancialCalculator
    from .models.orders import Order
    from .settings_store import settings_store

    stats = {"checked": 0, "updated": 0, "finalized": 0, "pending": 0, "errors": 0}

    try:
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")

        with get_session() as db:
            orders = (
                db.query(Order)
                .filter(
                    db_or(
                        Order.real_profit_amount.is_(None),
                        Order.real_profit_is_final.is_(False),
                        Order.real_profit_is_final.is_(None),
                    )
                )
                .filter(
                    db_or(
                        Order.payment_done > 0,
                        Order.payment_method_cod.is_(True),
                    )
                )
                .all()
            )

            if not orders:
                return stats

            calculator = FinancialCalculator(db, settings_store)
            prefetched_billings = calculator._prefetch_order_billing_summaries(
                orders,
                access_token,
                trace_label="scheduler-profit-cache",
            )

            logger.info(
                "Profit cache refresh: znaleziono %s zamowien do odswiezenia",
                len(orders),
            )

            for order in orders:
                try:
                    breakdown = calculator.refresh_order_profit_cache(
                        order,
                        access_token=access_token,
                        trace_label="scheduler-profit-cache",
                        prefetched_billing=prefetched_billings.get(order.external_order_id),
                    )
                    stats["checked"] += 1
                    stats["updated"] += 1
                    if breakdown.billing_complete:
                        stats["finalized"] += 1
                    else:
                        stats["pending"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    logger.warning(
                        "Profit cache refresh error: order_id=%s external_order_id=%s error=%s",
                        order.order_id,
                        order.external_order_id,
                        exc,
                    )

            db.commit()
    except Exception as exc:
        stats["errors"] += 1
        logger.error("Krytyczny blad odswiezania cache realnego zysku: %s", exc, exc_info=True)

    return stats


def _process_pending_invoices():
    """Automatyczne wystawianie faktur dla nowych zamowien z Allegro.

    Szuka zamowien ktore:
    - nie maja jeszcze wystawionej faktury (wfirma_invoice_id IS NULL)
    - maja przynajmniej jeden produkt
    - przyszly przez sync Allegro (order_id zaczyna sie od 'allegro_')

    Returns
    -------
    dict
        {"processed": int, "success": int, "errors": int}
    """
    from .db import get_session
    from .models.orders import Order
    from .services.invoice_service import generate_and_send_invoice

    stats = {"processed": 0, "success": 0, "errors": 0}

    # Tylko zamowienia z ostatnich 7 dni
    cutoff = int(time.time()) - 7 * 24 * 3600

    with get_session() as db:
        orders = (
            db.query(Order)
            .filter(
                Order.wfirma_invoice_id.is_(None),
                Order.date_add >= cutoff,
                Order.order_id.like("allegro_%"),
            )
            .all()
        )

        for order in orders:
            if not order.products:
                continue

            # Nie wystawiaj faktury jesli etykieta jeszcze nie zostala wygenerowana.
            # Brak etykiety moze oznaczac blad w adresie dostawy - co bedzie bledem
            # rowniez na fakturze. Poczekaj az print_agent potwierdzi wysylke.
            if not order.delivery_package_nr:
                logger.debug(
                    "Pomijam fakture dla %s - brak etykiety (delivery_package_nr)",
                    order.order_id,
                )
                continue

            stats["processed"] += 1
            try:
                result = generate_and_send_invoice(order.order_id)
                if result["success"]:
                    stats["success"] += 1
                    logger.info(
                        "Faktura %s wystawiona automatycznie dla %s",
                        result["invoice_number"], order.order_id,
                    )
                else:
                    stats["errors"] += 1
                    logger.warning(
                        "Blad wystawiania faktury dla %s: %s",
                        order.order_id, result["errors"],
                    )
            except Exception as exc:
                stats["errors"] += 1
                logger.error(
                    "Wyjatek przy wystawianiu faktury dla %s: %s",
                    order.order_id, exc,
                )

    return stats


def _cancel_stale_unpaid_orders():
    """Automatyczne anulowanie zamowien nieoplaconych przez 14 dni.

    Szuka zamowien, ktorych ostatni status to 'nieoplacone' i minelo
    wiecej niz 14 dni od momentu ustawienia tego statusu.

    Returns
    -------
    dict
        {"checked": int, "cancelled": int, "errors": int}
    """
    from .db import get_session
    from .models.orders import OrderStatusLog
    from .services.order_status import add_order_status
    from sqlalchemy import and_, func

    STALE_DAYS = 14
    stats = {"checked": 0, "cancelled": 0, "errors": 0}
    cutoff = datetime.utcnow() - timedelta(days=STALE_DAYS)

    try:
        with get_session() as db:
            # Znajdz ostatni status kazdego zamowienia
            latest_subq = (
                db.query(
                    OrderStatusLog.order_id,
                    func.max(OrderStatusLog.timestamp).label("max_ts"),
                )
                .group_by(OrderStatusLog.order_id)
                .subquery()
            )

            stale = (
                db.query(OrderStatusLog)
                .join(
                    latest_subq,
                    and_(
                        OrderStatusLog.order_id == latest_subq.c.order_id,
                        OrderStatusLog.timestamp == latest_subq.c.max_ts,
                    ),
                )
                .filter(
                    OrderStatusLog.status == "nieoplacone",
                    OrderStatusLog.timestamp < cutoff,
                )
                .all()
            )

            stats["checked"] = len(stale)
            for log_entry in stale:
                try:
                    add_order_status(
                        db,
                        log_entry.order_id,
                        "anulowano",
                        notes=f"Auto-anulowanie: nieoplacone przez {STALE_DAYS} dni",
                        send_email=False,
                    )
                    stats["cancelled"] += 1
                    logger.info(
                        "Auto-anulowanie: %s (nieoplacone od %s)",
                        log_entry.order_id,
                        log_entry.timestamp.isoformat(),
                    )
                except Exception as exc:
                    stats["errors"] += 1
                    logger.error(
                        "Blad auto-anulowania %s: %s",
                        log_entry.order_id, exc,
                    )

            db.commit()

    except Exception as exc:
        logger.error("Krytyczny blad auto-anulowania nieoplaconych: %s", exc, exc_info=True)
        stats["errors"] += 1

    return stats


def _set_last_offer_sync_date(value: str) -> None:
    global _last_offer_sync_date
    _last_offer_sync_date = value


def _order_sync_cycle() -> OrderSyncCycle:
    return OrderSyncCycle(
        logger=logger,
        callbacks=OrderSyncCallbacks(
            sync_from_allegro_events=_sync_from_allegro_events,
            refresh_order_profit_cache=_refresh_order_profit_cache,
            sync_allegro_fulfillment=_sync_allegro_fulfillment,
            process_pending_invoices=_process_pending_invoices,
            cancel_stale_unpaid_orders=_cancel_stale_unpaid_orders,
            get_last_offer_sync_date=lambda: _last_offer_sync_date,
            set_last_offer_sync_date=_set_last_offer_sync_date,
        ),
    )


def _run_allegro_events_sync(app) -> None:
    _order_sync_cycle().run_allegro_events_sync(app)


def _run_parcel_tracking_sync() -> None:
    _order_sync_cycle().run_parcel_tracking_sync()


def _run_profit_cache_refresh(app) -> None:
    _order_sync_cycle().run_profit_cache_refresh(app)


def _run_allegro_fulfillment_sync(app) -> None:
    _order_sync_cycle().run_allegro_fulfillment_sync(app)


def _run_returns_sync() -> None:
    _order_sync_cycle().run_returns_sync()


def _run_invoice_processing() -> None:
    _order_sync_cycle().run_invoice_processing()


def _run_unpaid_auto_cancel() -> None:
    _order_sync_cycle().run_unpaid_auto_cancel()


def _run_daily_allegro_offer_sync() -> None:
    _order_sync_cycle().run_daily_allegro_offer_sync()


def _run_daily_promo_sync() -> None:
    _order_sync_cycle().run_daily_promo_sync()


def _run_daily_offer_and_promo_sync() -> None:
    _order_sync_cycle().run_daily_offer_and_promo_sync()


def _run_order_sync_cycle(app) -> None:
    _order_sync_cycle().run(app)


def _sync_worker(app):
    """Background worker that syncs orders and parcel statuses every 10 minutes."""
    logger.info("Order sync scheduler started - will sync every 10 minutes")

    while not _stop_event.is_set():
        try:
            _run_order_sync_cycle(app)
        except Exception as e:
            logger.error(f"Error in automatic sync: {e}", exc_info=True)
        
        # Wait 10 minutes (600 seconds) or until stop event
        _stop_event.wait(600)
    
    logger.info("Order sync scheduler stopped")



def start_sync_scheduler(app):
    """Start the background order sync scheduler."""
    global _sync_thread
    
    _runtime.start(
        _sync_worker,
        app,
        already_running_message="Order sync scheduler already running",
        started_message="Order sync scheduler thread started",
    )
    _sync_thread = _runtime.thread


def stop_sync_scheduler():
    """Stop the background order sync scheduler."""
    global _sync_thread
    
    _runtime.stop(
        stopping_message="Stopping order sync scheduler...",
        stopped_message="Order sync scheduler stopped",
    )
    _sync_thread = None
