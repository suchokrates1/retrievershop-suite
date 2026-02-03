"""
Background scheduler dla codziennego sprawdzania wyrozien Allegro.

Sprawdza raz dziennie o ustalonej godzinie czy sa wyroznienia
ktore przedluza sie nastepnego dnia i wysyla powiadomienia.
"""

import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_promo_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()

# Godzina sprawdzania wyrozien (domyslnie 18:00 - wieczorem przed przedluzeniem)
CHECK_HOUR = 18
CHECK_MINUTE = 0


def _calculate_seconds_until_check() -> int:
    """
    Oblicza ile sekund do nastepnego sprawdzenia.
    
    Sprawdzanie odbywa sie o CHECK_HOUR:CHECK_MINUTE kazdego dnia.
    Jesli ta godzina dzisiaj juz minela, czekamy do jutro.
    """
    now = datetime.now()
    next_check = now.replace(hour=CHECK_HOUR, minute=CHECK_MINUTE, second=0, microsecond=0)
    
    if now >= next_check:
        # Dzisiejsze sprawdzenie juz minelo, czekamy do jutro
        next_check = next_check + timedelta(days=1)
    
    delta = next_check - now
    return int(delta.total_seconds())


def _promo_worker(app):
    """
    Background worker sprawdzajacy wyroznienia raz dziennie.
    
    Sprawdza o godzinie CHECK_HOUR:CHECK_MINUTE i wysyla powiadomienia
    o wyroznieniach ktore przedluza sie nastepnego dnia.
    """
    from .services.allegro_promotions import check_and_notify_promotions
    
    logger.info(f"Promo scheduler started - will check daily at {CHECK_HOUR:02d}:{CHECK_MINUTE:02d}")
    
    while not _stop_event.is_set():
        # Oblicz czas do nastepnego sprawdzenia
        wait_seconds = _calculate_seconds_until_check()
        logger.info(f"Next promo check in {wait_seconds // 3600}h {(wait_seconds % 3600) // 60}m")
        
        # Czekaj do czasu sprawdzenia lub sygnalu zatrzymania
        if _stop_event.wait(wait_seconds):
            # Stop event zostal ustawiony
            break
        
        # Czas sprawdzenia
        try:
            with app.app_context():
                logger.info("Starting daily promo check")
                result = check_and_notify_promotions(app)
                
                if result['error']:
                    logger.error(f"Promo check error: {result['error']}")
                else:
                    logger.info(
                        f"Promo check completed: "
                        f"active={result['active_count']}, "
                        f"renewing_tomorrow={result['renewing_tomorrow']}, "
                        f"notification_sent={result['notification_sent']}"
                    )
                    
        except Exception as e:
            logger.error(f"Error in promo check: {e}", exc_info=True)
        
        # Dodatkowe male opoznienie zeby uniknac wielokrotnego sprawdzenia
        # w tej samej minucie
        _stop_event.wait(60)
    
    logger.info("Promo scheduler stopped")


def start_promo_scheduler(app):
    """Uruchamia scheduler sprawdzania wyrozien."""
    global _promo_thread
    
    if _promo_thread is not None and _promo_thread.is_alive():
        logger.warning("Promo scheduler already running")
        return
    
    _stop_event.clear()
    _promo_thread = threading.Thread(
        target=_promo_worker,
        args=(app,),
        daemon=True,
        name="PromoScheduler"
    )
    _promo_thread.start()
    logger.info("Promo scheduler thread started")


def stop_promo_scheduler():
    """Zatrzymuje scheduler sprawdzania wyrozien."""
    global _promo_thread
    
    if _promo_thread is None or not _promo_thread.is_alive():
        logger.info("Promo scheduler not running")
        return
    
    logger.info("Stopping promo scheduler...")
    _stop_event.set()
    _promo_thread.join(timeout=5)
    _promo_thread = None
    logger.info("Promo scheduler stopped")


def run_promo_check_now(app) -> dict:
    """
    Wymusza natychmiastowe sprawdzenie wyrozien.
    
    Uzyteczne do testowania lub recznego uruchomienia.
    
    Returns:
        Dict z wynikiem sprawdzenia
    """
    from .services.allegro_promotions import check_and_notify_promotions
    
    logger.info("Running manual promo check")
    
    with app.app_context():
        return check_and_notify_promotions(app)
