"""Background scheduler for automatic order synchronization."""

import threading
import time
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_sync_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_last_offer_sync_date: Optional[str] = None  # YYYY-MM-DD - data ostatniego syncu ofert


def _sync_from_allegro_events(app):
    """Synchronizuj zamowienia z Allegro przez Events API (inkrementalnie).

    Mechanizm event-driven polling:
    1. Wczytaj ALLEGRO_LAST_EVENT_ID z settings_store
    2. Pobierz zdarzenia od tego ID (GET /order/events?from=...)
    3. Dla BOUGHT/FILLED_IN/READY_FOR_PROCESSING: pobierz szczegoly -> sync_order_from_data()
    4. Dla BUYER_CANCELLED / AUTO_CANCELLED: aktualizuj status
    5. Zapisz nowy last_event_id
    """
    from .db import get_session
    from .orders import sync_order_from_data, add_order_status
    from .allegro_api.events import fetch_order_events, fetch_event_stats
    from .allegro_api.orders import (
        fetch_allegro_order_detail,
        parse_allegro_order_to_data,
        get_allegro_internal_status,
    )
    from .settings_store import settings_store

    stats = {
        "events_fetched": 0,
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
                seen_checkout_forms = set()

                for event in all_events:
                    event_type = event.get("type", "")
                    order_info = event.get("order", {})
                    checkout_form_id = order_info.get("checkoutForm", {}).get("id")

                    if not checkout_form_id:
                        continue

                    # Deduplikacja - jedno zamowienie moze miec wiele zdarzen
                    event_key = (checkout_form_id, event_type)
                    if event_key in seen_checkout_forms:
                        stats["orders_skipped"] += 1
                        continue
                    seen_checkout_forms.add(event_key)

                    if event_type in ("BOUGHT", "FILLED_IN", "READY_FOR_PROCESSING"):
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

                    elif event_type in ("BUYER_CANCELLED", "AUTO_CANCELLED"):
                        try:
                            order_id = f"allegro_{checkout_form_id}"
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

                    else:
                        stats["orders_skipped"] += 1

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
                        new_status = derived_status
                        if not new_status:
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


def _process_pending_invoices():
    """Automatyczne wystawianie faktur dla nowych zamowien z Allegro.

    Szuka zamowien ktore:
    - nie maja jeszcze wystawionej faktury (wfirma_invoice_id IS NULL)
    - maja przynajmniej jeden produkt
    - przyszly przez sync Allegro (order_id zaczyna sie od 'allegro_')

    Stare zamowienia z BaseLinker nie sa przetwarzane -
    mialy faktury wystawiane recznie w wFirma.

    Returns
    -------
    dict
        {"processed": int, "success": int, "errors": int}
    """
    from .db import get_session
    from .models import Order
    from .services.invoice_service import generate_and_send_invoice
    import time

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


def _sync_worker(app):
    """Background worker that syncs orders and parcel statuses every 10 minutes."""
    from .parcel_tracking import sync_parcel_statuses
    from .returns import sync_returns
    
    global _last_offer_sync_date
    
    logger.info("Order sync scheduler started - will sync every 10 minutes")
    
    while not _stop_event.is_set():
        try:
            with app.app_context():
                # 0. Sync zamowien z Allegro Events API (inkrementalny)
                logger.info("Starting Allegro Events sync")
                ev_stats = _sync_from_allegro_events(app)
                logger.info(
                    f"Allegro Events sync completed: events={ev_stats['events_fetched']}, "
                    f"synced={ev_stats['orders_synced']}, cancelled={ev_stats['orders_cancelled']}, "
                    f"errors={ev_stats['errors']}"
                )

                # 1. Sync parcel tracking statuses from Allegro
                logger.info("Starting automatic parcel tracking sync")
                stats = sync_parcel_statuses()
                logger.info(
                    f"Parcel tracking sync completed: checked={stats['checked']}, "
                    f"updated={stats['updated']}, errors={stats['errors']}"
                )
                
                # 2. Sync fulfillment status z Allegro checkout-forms API
                logger.info("Starting Allegro fulfillment sync")
                f_stats = _sync_allegro_fulfillment(app)
                logger.info(
                    f"Allegro fulfillment sync completed: checked={f_stats['checked']}, "
                    f"updated={f_stats['updated']}, errors={f_stats['errors']}"
                )
                
                # 3. Sync returns - sprawdz zwroty, wyslij powiadomienia, aktualizuj stany
                logger.info("Starting automatic returns sync")
                returns_stats = sync_returns()
                logger.info(f"Returns sync completed: {returns_stats}")

                # 4. Automatyczne wystawianie faktur dla zamowien z want_invoice
                try:
                    inv_stats = _process_pending_invoices()
                    if inv_stats["processed"] > 0:
                        logger.info(
                            f"Invoice processing: processed={inv_stats['processed']}, "
                            f"success={inv_stats['success']}, errors={inv_stats['errors']}"
                        )
                except Exception as inv_err:
                    logger.error(f"Error in invoice processing: {inv_err}", exc_info=True)
                
                # 5. Codzienny sync ofert Allegro (raz dziennie)
                today = datetime.now().strftime("%Y-%m-%d")
                if _last_offer_sync_date != today:
                    logger.info("Starting daily Allegro offer sync")
                    try:
                        from .allegro_sync import sync_offers
                        offer_stats = sync_offers()
                        _last_offer_sync_date = today
                        logger.info(f"Daily offer sync completed: {offer_stats}")
                    except Exception as offer_err:
                        logger.error(f"Error in daily offer sync: {offer_err}", exc_info=True)
                    
                    # 6. Sync promowanych ofert Allegro (raz dziennie)
                    logger.info("Starting daily promo sync")
                    try:
                        from .services.allegro_promotions import get_promotions_summary
                        promo_summary = get_promotions_summary()
                        if promo_summary.error:
                            logger.warning(f"Promo sync warning: {promo_summary.error}")
                        else:
                            logger.info(
                                f"Promo sync completed: active={promo_summary.active_count}, "
                                f"renewing_tomorrow={len(promo_summary.renewing_tomorrow)}"
                            )
                    except Exception as promo_err:
                        logger.error(f"Error in promo sync: {promo_err}", exc_info=True)
                else:
                    logger.debug("Offer sync already done today, skipping")
                
        except Exception as e:
            logger.error(f"Error in automatic sync: {e}", exc_info=True)
        
        # Wait 10 minutes (600 seconds) or until stop event
        _stop_event.wait(600)
    
    logger.info("Order sync scheduler stopped")



def start_sync_scheduler(app):
    """Start the background order sync scheduler."""
    global _sync_thread
    
    if _sync_thread is not None and _sync_thread.is_alive():
        logger.warning("Order sync scheduler already running")
        return
    
    _stop_event.clear()
    _sync_thread = threading.Thread(
        target=_sync_worker,
        args=(app,),
        daemon=True,
        name="OrderSyncScheduler"
    )
    _sync_thread.start()
    logger.info("Order sync scheduler thread started")


def stop_sync_scheduler():
    """Stop the background order sync scheduler."""
    global _sync_thread
    
    if _sync_thread is None or not _sync_thread.is_alive():
        logger.info("Order sync scheduler not running")
        return
    
    logger.info("Stopping order sync scheduler...")
    _stop_event.set()
    _sync_thread.join(timeout=5)
    _sync_thread = None
    logger.info("Order sync scheduler stopped")
