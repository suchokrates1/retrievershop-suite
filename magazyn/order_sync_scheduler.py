"""Background scheduler for automatic order synchronization."""

import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from .services.order_sync_cycle import OrderSyncCallbacks, OrderSyncCycle
from .services.runtime import BackgroundThreadRuntime

logger = logging.getLogger(__name__)

_sync_thread: Optional[threading.Thread] = None
_runtime = BackgroundThreadRuntime(name="OrderSyncScheduler", logger=logger)
_stop_event = _runtime.stop_event
_last_offer_sync_date: Optional[str] = None  # YYYY-MM-DD - data ostatniego syncu ofert


def _sync_from_allegro_events(app):
    """Synchronizuj zamowienia z Allegro przez Events API (inkrementalnie).

    Mechanizm event-driven polling:
    1. Wczytaj ALLEGRO_LAST_EVENT_ID z settings_store
    2. Pobierz zdarzenia od tego ID (GET /order/events?from=...)
    3. Dla BOUGHT/FILLED_IN/READY_FOR_PROCESSING: pobierz szczegoly -> sync_order_from_data()
    4. Dla BUYER_CANCELLED / AUTO_CANCELLED: aktualizuj status
    5. Zapisz raw events do OrderEvent tabeli dla analizy funnelu
    6. Zapisz nowy last_event_id
    """
    from .db import get_session
    from .models import OrderEvent
    from .orders import sync_order_from_data, add_order_status
    from .allegro_api.events import fetch_order_events, fetch_event_stats
    from .allegro_api.orders import (
        fetch_allegro_order_detail,
        parse_allegro_order_to_data,
        get_allegro_internal_status,
    )
    from .settings_store import settings_store
    from sqlalchemy.exc import IntegrityError
    from dateutil import parser as dateparser

    stats = {
        "events_fetched": 0,
        "events_stored": 0,
        "orders_synced": 0,
        "orders_cancelled": 0,
        "orders_skipped": 0,
        "errors": 0,
    }

    try:
        last_event_id = settings_store.get("ALLEGRO_LAST_EVENT_ID")

        # Przy pierwszym uruchomieniu - inicjalizuj kursor na najnowszym zdarzeniu
        if not last_event_id:
            logger.info("Allegro Events: brak kursora, inicjalizacja na najnowszym zdarzeniu")
            try:
                event_stats = fetch_event_stats()
                latest = event_stats.get("latestEvent", {})
                last_event_id = latest.get("id")
                if last_event_id:
                    settings_store.update({"ALLEGRO_LAST_EVENT_ID": last_event_id})
                    logger.info(f"Allegro Events: kursor zainicjalizowany na {last_event_id}")
                else:
                    logger.warning("Allegro Events: brak zdarzen do inicjalizacji")
                return stats
            except Exception as exc:
                logger.error(f"Allegro Events: blad inicjalizacji kursora: {exc}")
                stats["errors"] += 1
                return stats

        # Pobierz zdarzenia inkrementalnie
        all_events = []
        current_from = last_event_id
        max_pages = 10  # zabezpieczenie przed nieskonczonym pollingiem

        for _ in range(max_pages):
            try:
                result = fetch_order_events(from_event_id=current_from, limit=1000)
            except Exception as exc:
                logger.error(f"Allegro Events: blad pobierania zdarzen: {exc}")
                stats["errors"] += 1
                break

            events = result.get("events", [])
            if not events:
                break

            all_events.extend(events)
            current_from = events[-1].get("id")

            # Jesli mniej niz limit - to ostatnia strona
            if len(events) < 1000:
                break

        stats["events_fetched"] = len(all_events)

        if not all_events:
            logger.debug("Allegro Events: brak nowych zdarzen")
            return stats

        logger.info(f"Allegro Events: pobrano {len(all_events)} nowych zdarzen")

        # Przetwarzaj zdarzenia
        with app.app_context():
            with get_session() as db:
                seen_import_checkout_forms = set()
                import_event_types = {"BOUGHT", "FILLED_IN", "READY_FOR_PROCESSING"}

                for event in all_events:
                    event_id = event.get("id", "")
                    event_type = event.get("type", "")
                    order_info = event.get("order", {})
                    checkout_form_id = order_info.get("checkoutForm", {}).get("id")
                    occurred_at_str = event.get("occurredAt", "")

                    if not checkout_form_id:
                        continue

                    # Parsuj timestamp zdarzenia
                    try:
                        occurred_at = dateparser.isoparse(occurred_at_str) if occurred_at_str else datetime.now(timezone.utc)
                    except Exception:
                        occurred_at = datetime.now(timezone.utc)

                    order_id = f"allegro_{checkout_form_id}"

                    # Deduplikacja importu - w jednej partii jedno zamowienie
                    # moze miec kilka eventow zakupowych (np. BOUGHT/FILLED_IN/
                    # READY_FOR_PROCESSING). Pelny sync wykonujemy tylko raz,
                    # ale raw event zapisujemy zawsze do analizy.
                    if event_type in import_event_types and checkout_form_id in seen_import_checkout_forms:
                        stats["orders_skipped"] += 1
                        # Zapisz raw event nawet dla deduplikowanych zdarzen (analiza funnelu)
                        try:
                            nested = db.begin_nested()
                            event_record = OrderEvent(
                                order_id=order_id,
                                allegro_event_id=event_id,
                                event_type=event_type,
                                occurred_at=occurred_at,
                                payload_json=str(event),
                            )
                            db.add(event_record)
                            db.flush()
                            stats["events_stored"] += 1
                        except IntegrityError:
                            nested.rollback()
                        except Exception:
                            nested.rollback()
                        continue
                    if event_type in import_event_types:
                        seen_import_checkout_forms.add(checkout_form_id)

                    if event_type in import_event_types:
                        try:
                            detail = fetch_allegro_order_detail(checkout_form_id)
                            order_data = parse_allegro_order_to_data(detail)
                            sync_order_from_data(db, order_data)
                            internal_status = get_allegro_internal_status(order_data)
                            add_order_status(
                                db,
                                order_data["order_id"],
                                internal_status,
                                notes=f"Allegro event: {event_type}",
                            )
                            stats["orders_synced"] += 1
                            logger.info(
                                f"Allegro Events: zsynchronizowano zamowienie "
                                f"{checkout_form_id}"
                            )
                        except Exception as exc:
                            logger.error(
                                f"Allegro Events: blad syncu zamowienia "
                                f"{checkout_form_id}: {exc}"
                            )
                            stats["errors"] += 1
                            continue

                    elif event_type in ("BUYER_CANCELLED", "AUTO_CANCELLED"):
                        try:
                            add_order_status(
                                db,
                                order_id,
                                "anulowano",
                                notes=f"Allegro event: {event_type}",
                            )
                            stats["orders_cancelled"] += 1
                            logger.info(
                                f"Allegro Events: anulowano zamowienie "
                                f"{checkout_form_id} ({event_type})"
                            )
                        except Exception as exc:
                            logger.warning(
                                f"Allegro Events: blad anulowania "
                                f"{checkout_form_id}: {exc}"
                            )
                            stats["errors"] += 1
                            continue

                    else:
                        stats["orders_skipped"] += 1
                        continue

                    # Zapisz raw event PO syncu zamowienia (Order musi istniec dla FK)
                    try:
                        nested = db.begin_nested()
                        event_record = OrderEvent(
                            order_id=order_id,
                            allegro_event_id=event_id,
                            event_type=event_type,
                            occurred_at=occurred_at,
                            payload_json=str(event),
                        )
                        db.add(event_record)
                        db.flush()
                        stats["events_stored"] += 1
                        logger.debug(f"Allegro Events: zapisano raw event {event_id}")
                    except IntegrityError:
                        nested.rollback()
                        logger.debug(f"Allegro Events: event {event_id} juz istnieje, pominieto")
                    except Exception as exc:
                        nested.rollback()
                        logger.warning(f"Allegro Events: blad zapisu raw event {event_id}: {exc}")

                db.commit()

        # Zapisz kursor na ostatnim przetworzonym zdarzeniu
        new_last_id = all_events[-1].get("id")
        if new_last_id:
            settings_store.update({"ALLEGRO_LAST_EVENT_ID": new_last_id})
            logger.info(f"Allegro Events: kursor zaktualizowany na {new_last_id}")

    except Exception as exc:
        logger.error(f"Allegro Events: krytyczny blad: {exc}", exc_info=True)
        stats["errors"] += 1

    return stats


def _sync_allegro_fulfillment(app):
    """Synchronizuj statusy realizacji zamowien z Allegro API (fulfillment.status).
    
    Allegro Parcel Tracking API czesto nie zwraca eventow dla niektorych
    typow przesylek (np. miniKurier24). Dlatego uzywamy checkout-forms API
    do aktualizacji statusow na podstawie fulfillment.status (SENT, PICKED_UP itp.).
    
    Sprawdzamy tylko zamowienia ktore:
    - maja external_order_id (UUID Allegro)
    - sa w statusie posrednim (wydrukowano, spakowano, wyslano, w_transporcie, w_punkcie)
    """
    from .db import get_session
    from .models import Order, OrderStatusLog
    from .orders import add_order_status
    from .allegro_api.orders import (
        fetch_allegro_order_detail,
        parse_allegro_order_to_data,
        get_allegro_internal_status,
        ALLEGRO_FULFILLMENT_MAP,
    )
    from sqlalchemy import and_, desc, func
    
    stats = {"checked": 0, "updated": 0, "errors": 0, "skipped": 0}
    
    try:
        with get_session() as db:
            # Znajdz ostatni status kazdego zamowienia
            latest_status_subq = (
                db.query(
                    OrderStatusLog.order_id,
                    func.max(OrderStatusLog.timestamp).label("max_ts")
                )
                .group_by(OrderStatusLog.order_id)
                .subquery()
            )
            
            # Zamowienia w statusach posrednich z external_order_id
            active_statuses = ["wydrukowano", "spakowano", "wyslano", "w_transporcie", "w_punkcie"]
            orders = (
                db.query(Order)
                .join(OrderStatusLog, OrderStatusLog.order_id == Order.order_id)
                .join(
                    latest_status_subq,
                    and_(
                        OrderStatusLog.order_id == latest_status_subq.c.order_id,
                        OrderStatusLog.timestamp == latest_status_subq.c.max_ts,
                    ),
                )
                .filter(
                    OrderStatusLog.status.in_(active_statuses),
                    Order.external_order_id.isnot(None),
                    Order.external_order_id != "",
                )
                .distinct()
                .all()
            )
            
            logger.info(f"Allegro fulfillment sync: {len(orders)} zamowien do sprawdzenia")
            
            for order in orders:
                try:
                    detail = fetch_allegro_order_detail(order.external_order_id)
                    stats["checked"] += 1

                    # Priorytet: status checkout-form (np. CANCELLED) nad samym fulfillment.
                    # To domyka przypadki, gdzie fulfillment jeszcze nie odzwierciedla anulowania.
                    parsed = parse_allegro_order_to_data(detail)
                    derived_status = get_allegro_internal_status(parsed)
                    
                    fulfillment = detail.get("fulfillment", {}) or {}
                    f_status = fulfillment.get("status", "")
                    
                    if not f_status:
                        stats["skipped"] += 1
                        continue
                    
                    new_status = ALLEGRO_FULFILLMENT_MAP.get(f_status)
                    if not new_status:
                        if derived_status == "anulowano":
                            new_status = "anulowano"
                        else:
                            stats["skipped"] += 1
                            continue

                    if derived_status == "anulowano":
                        new_status = "anulowano"
                    
                    # Pobierz obecny status
                    current_log = (
                        db.query(OrderStatusLog)
                        .filter(OrderStatusLog.order_id == order.order_id)
                        .order_by(desc(OrderStatusLog.timestamp))
                        .first()
                    )
                    current_status = current_log.status if current_log else None
                    
                    if current_status != new_status:
                        logger.info(
                            f"Allegro fulfillment: {order.order_id} "
                            f"{current_status} -> {new_status} (fulfillment: {f_status})"
                        )
                        add_order_status(
                            db,
                            order.order_id,
                            new_status,
                            notes=f"Allegro fulfillment sync: {f_status}",
                        )
                        stats["updated"] += 1
                    
                except Exception as exc:
                    logger.warning(
                        f"Blad sprawdzania fulfillment dla {order.order_id}: {exc}"
                    )
                    stats["errors"] += 1
            
            db.commit()
    
    except Exception as exc:
        logger.error(f"Krytyczny blad sync fulfillment: {exc}", exc_info=True)
        stats["errors"] += 1
    
    return stats


def _refresh_order_profit_cache(app):
    """Odswieza zapisany realny zysk dla zamowien bez finalnych danych billingowych."""
    from sqlalchemy import or_ as db_or

    from .db import get_session
    from .domain.financial import FinancialCalculator
    from .models import Order
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
                        Order.payment_method_cod == True,
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
    from .models import Order
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
    from .models import OrderStatusLog
    from .orders import add_order_status
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
