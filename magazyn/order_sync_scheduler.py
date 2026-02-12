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


def _sync_allegro_fulfillment(app):
    """Synchronizuj statusy realizacji zamowien z Allegro API (fulfillment.status).
    
    Allegro Parcel Tracking API czesto nie zwraca eventow dla niektorych
    typow przesylek (np. miniKurier24). Dlatego uzywamy checkout-forms API
    do aktualizacji statusow na podstawie fulfillment.status (SENT, PICKED_UP itp.).
    
    Sprawdzamy tylko zamowienia ktore:
    - maja external_order_id (UUID Allegro)
    - sa w statusie posrednim (wydrukowano, spakowano, przekazano_kurierowi, w_drodze, w_punkcie)
    """
    from .db import get_session
    from .models import Order, OrderStatusLog
    from .orders import add_order_status
    from .allegro_api.orders import (
        fetch_allegro_order_detail,
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
            active_statuses = ["wydrukowano", "spakowano", "przekazano_kurierowi", "w_drodze", "w_punkcie", "gotowe_do_odbioru"]
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
                    
                    fulfillment = detail.get("fulfillment", {}) or {}
                    f_status = fulfillment.get("status", "")
                    
                    if not f_status:
                        stats["skipped"] += 1
                        continue
                    
                    new_status = ALLEGRO_FULFILLMENT_MAP.get(f_status)
                    if not new_status:
                        stats["skipped"] += 1
                        continue
                    
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


def _sync_worker(app):
    """Background worker that syncs orders and parcel statuses every hour."""
    from .orders import _sync_orders_from_baselinker, ALL_STATUS_IDS
    from .parcel_tracking import sync_parcel_statuses
    from .returns import sync_returns
    
    global _last_offer_sync_date
    
    logger.info("Order sync scheduler started - will sync every 1 hour")
    
    while not _stop_event.is_set():
        try:
            with app.app_context():
                # 1. Sync orders from BaseLinker
                logger.info("Starting automatic order sync (last 30 days, all statuses)")
                synced = _sync_orders_from_baselinker(ALL_STATUS_IDS, days=30)
                logger.info(f"Automatic order sync completed: {synced} orders synced")
                
                # 2. Sync parcel tracking statuses from Allegro
                logger.info("Starting automatic parcel tracking sync")
                stats = sync_parcel_statuses()
                logger.info(
                    f"Parcel tracking sync completed: checked={stats['checked']}, "
                    f"updated={stats['updated']}, errors={stats['errors']}"
                )
                
                # 3. Sync fulfillment status z Allegro checkout-forms API
                logger.info("Starting Allegro fulfillment sync")
                f_stats = _sync_allegro_fulfillment(app)
                logger.info(
                    f"Allegro fulfillment sync completed: checked={f_stats['checked']}, "
                    f"updated={f_stats['updated']}, errors={f_stats['errors']}"
                )
                
                # 4. Sync returns - sprawdz zwroty, wyslij powiadomienia, aktualizuj stany
                logger.info("Starting automatic returns sync")
                returns_stats = sync_returns()
                logger.info(f"Returns sync completed: {returns_stats}")
                
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
                    
                    # 6. Sync wyrozien Allegro (razem z ofertami, raz dziennie)
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
        
        # Wait 1 hour (3600 seconds) or until stop event
        _stop_event.wait(3600)
    
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
