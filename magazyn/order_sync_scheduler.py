"""Background scheduler for automatic order synchronization."""

import threading
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_sync_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _sync_worker(app):
    """Background worker that syncs orders and parcel statuses every hour."""
    from .orders import _sync_orders_from_baselinker, ALL_STATUS_IDS
    from .parcel_tracking import sync_parcel_statuses
    
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
