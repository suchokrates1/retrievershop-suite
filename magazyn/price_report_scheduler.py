"""
Scheduler dla automatycznego generowania raportow cenowych.

Harmonogram:
- Start: piatek 16:00
- Koniec: niedziela 16:00
- Przerwy nocne: 02:00 - 06:00
- Powiadomienie: niedziela po 16:00

Logika:
1. W piatek o 16:00 scheduler tworzy nowy raport i oblicza harmonogram
2. Oferty sa sprawdzane partiami z losowymi odstepami
3. Pomija przerwy nocne
4. Po zakonczeniu wysyla powiadomienie
"""

import threading
import time
import random
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import func, distinct

from .services.price_report_checker import check_single_offer
from .services.price_report_processing import (
    count_checked_offers as _count_checked_offers,
    create_new_report,
    finalize_report,
    get_active_offers_count,
    get_unchecked_offers,
    mark_sibling_offers,
    save_report_item,
)
from .services.price_report_schedule import (
    calculate_schedule as _calculate_schedule,
    is_night_pause_at,
)
from .services.runtime import BackgroundThreadRuntime

logger = logging.getLogger(__name__)

_scheduler_thread: Optional[threading.Thread] = None
_runtime = BackgroundThreadRuntime(name="PriceReportScheduler", logger=logger)
_stop_event = _runtime.stop_event
_current_report_id: Optional[int] = None
_worker_lock = threading.Lock()          # zapobiega rownoleglosci workerow
_active_worker_thread: Optional[threading.Thread] = None


# Konfiguracja czasowa
FRIDAY_START_HOUR = 16  # Piatek 16:00
SUNDAY_END_HOUR = 16    # Niedziela 16:00
NIGHT_PAUSE_START = 2   # Przerwa nocna od 02:00
NIGHT_PAUSE_END = 6     # Przerwa nocna do 06:00
BATCH_SIZE = 5          # Ofert w partii
MIN_BATCH_DELAY = 3 * 60   # Min 3 min miedzy partiami
MAX_BATCH_DELAY = 6 * 60   # Max 6 min miedzy partiami
MANUAL_MIN_BATCH_DELAY = MIN_BATCH_DELAY
MANUAL_MAX_BATCH_DELAY = MAX_BATCH_DELAY


def is_night_pause() -> bool:
    """Sprawdza czy jest przerwa nocna."""
    return is_night_pause_at(
        datetime.now(),
        night_start=NIGHT_PAUSE_START,
        night_end=NIGHT_PAUSE_END,
    )


def calculate_schedule(total_offers: int, start_time: datetime, end_time: datetime) -> List[datetime]:
    """
    Oblicza harmonogram sprawdzania ofert.
    
    Rozklada oferty rownomiernie z losowymi odchyleniami,
    pomijajac przerwy nocne.
    """
    return _calculate_schedule(
        total_offers,
        start_time,
        end_time,
        batch_size=BATCH_SIZE,
        night_pause_start=NIGHT_PAUSE_START,
        night_pause_end=NIGHT_PAUSE_END,
    )


def sync_allegro_offers_before_report():
    """Synchronizuje oferty z Allegro przed utworzeniem raportu."""
    try:
        from .allegro_sync import sync_offers
        logger.info("Rozpoczynam synchronizacje ofert z Allegro...")
        result = sync_offers()
        logger.info(f"Synchronizacja zakonczona: pobrano {result.get('fetched', 0)}, dopasowano {result.get('matched', 0)}")
        return result
    except Exception as e:
        logger.error(f"Blad synchronizacji ofert: {e}")
        return None


def send_report_notification(report_id: int):
    """Wysyla powiadomienie o gotowym raporcie."""
    from .db import get_session
    from .models import PriceReport, PriceReportItem
    from .notifications.messenger import MessengerClient, MessengerConfig
    from .settings_store import settings_store
    
    try:
        with get_session() as session:
            report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
            if not report:
                return
            
            total = session.query(func.count(distinct(PriceReportItem.offer_id))).filter(
                PriceReportItem.report_id == report_id
            ).scalar() or 0
            
            cheapest = session.query(func.count(distinct(PriceReportItem.offer_id))).filter(
                PriceReportItem.report_id == report_id,
                PriceReportItem.is_cheapest == True
            ).scalar() or 0
            
            not_cheapest = total - cheapest
        
        access_token = settings_store.get("PAGE_ACCESS_TOKEN", "")
        recipient_id = settings_store.get("RECIPIENT_ID", "")
        
        if not access_token or not recipient_id:
            logger.warning("Brak konfiguracji Messenger - pomijam powiadomienie")
            return
        
        config = MessengerConfig(
            access_token=access_token,
            recipient_id=recipient_id,
        )
        client = MessengerClient(config)
        
        message = (
            f"Raport cenowy #{report_id} gotowy!\n\n"
            f"Sprawdzono: {total} ofert\n"
            f"Najtansi: {cheapest}\n"
            f"Drozsi od konkurencji: {not_cheapest}\n\n"
            f"Sprawdz szczegoly w aplikacji."
        )
        
        if client.send_text(message):
            logger.info(f"Wyslano powiadomienie o raporcie #{report_id}")
        else:
            logger.error("Nie udalo sie wyslac powiadomienia")
            
    except Exception as e:
        logger.error(f"Blad wysylania powiadomienia: {e}", exc_info=True)


def _start_worker(app, report_id: int, schedule: List[datetime], fast_mode: bool = True) -> bool:
    """Uruchamia workera jesli zaden inny nie jest aktywny. Zwraca True jesli uruchomiono."""
    global _active_worker_thread
    with _worker_lock:
        if _active_worker_thread is not None and _active_worker_thread.is_alive():
            logger.warning(f"Worker juz dziala ({_active_worker_thread.name}) - pomijam uruchomienie dla raportu #{report_id}")
            return False
        worker = threading.Thread(
            target=_report_worker,
            args=(app, report_id, schedule),
            kwargs={"fast_mode": fast_mode},
            daemon=True,
            name=f"PriceReportWorker-{report_id}"
        )
        _active_worker_thread = worker
        worker.start()
        return True


def _report_worker(app, report_id: int, schedule: List[datetime], fast_mode: bool = False):
    """Worker przetwarzajacy raport.
    
    fast_mode=True: tryb reczny - pomija pauze nocna i czeka losowo
    MANUAL_MIN_BATCH_DELAY..MANUAL_MAX_BATCH_DELAY minut miedzy partiami.
    """
    import asyncio
    from .scripts.price_checker_ws import CDP_HOST, CDP_PORT
    
    mode_label = "reczny" if fast_mode else "wolny"
    logger.info(f"Rozpoczynam przetwarzanie raportu #{report_id}, {len(schedule)} partii (tryb: {mode_label})")
    
    # Przed scrapingiem oznacz drozsze siostry jako "Inna OK"
    try:
        with app.app_context():
            sibling_count = mark_sibling_offers(report_id)
            if sibling_count > 0:
                logger.info(f"Pominiento {sibling_count} ofert (Inna OK) - zostaly drozsze siostry")
    except Exception as e:
        logger.warning(f"Blad oznaczania siostrzanych ofert: {e}")
    
    batch_idx = 0
    
    while not _stop_event.is_set() and batch_idx < len(schedule):
        if not fast_mode:
            # Czekaj na zaplanowany czas (tylko tryb automatyczny)
            target_time = schedule[batch_idx]
            now = datetime.now()
            
            if now < target_time:
                wait_seconds = (target_time - now).total_seconds()
                logger.info(f"Czekam {wait_seconds/60:.1f} min do partii {batch_idx + 1}")
                
                if _stop_event.wait(wait_seconds):
                    logger.info("Przerwano oczekiwanie")
                    break
            
            # Sprawdz czy nie jest przerwa nocna (tylko tryb automatyczny)
            if is_night_pause():
                logger.info("Przerwa nocna - czekam do 06:00")
                now = datetime.now()
                wake_time = now.replace(hour=NIGHT_PAUSE_END, minute=0, second=0)
                if now.hour >= NIGHT_PAUSE_END:
                    wake_time += timedelta(days=1)
                wait_seconds = (wake_time - now).total_seconds()
                _stop_event.wait(wait_seconds)
                continue
        
        try:
            with app.app_context():
                # Pobierz oferty do sprawdzenia
                offers = get_unchecked_offers(report_id, BATCH_SIZE)
                
                if not offers:
                    logger.info("Brak wiecej ofert do sprawdzenia")
                    break
                
                logger.info(f"Partia {batch_idx + 1}: sprawdzam {len(offers)} ofert")
                
                # Sprawdz kazda oferte
                for offer in offers:
                    if _stop_event.is_set():
                        break
                    
                    try:
                        # Uruchom async check
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        result = loop.run_until_complete(
                            check_single_offer(offer, CDP_HOST, CDP_PORT)
                        )
                        loop.close()
                        
                        # Zapisz wynik
                        save_report_item(report_id, result)
                        logger.info(f"Sprawdzono: {offer['offer_id']} - {'OK' if result['success'] else result['error']}")
                        
                        # Losowe opoznienie miedzy ofertami w partii (2-5 sek)
                        time.sleep(random.uniform(2, 5))  # nosec B311
                        
                    except Exception as e:
                        logger.error(f"Blad sprawdzania oferty {offer['offer_id']}: {e}")
                        # Zapisz blad
                        save_report_item(report_id, {
                            **offer,
                            "success": False,
                            "error": str(e),
                            "my_position": 0,
                            "competitors_count": 0,
                            "cheapest": None,
                        })
                
        except Exception as e:
            logger.error(f"Blad partii {batch_idx + 1}: {e}", exc_info=True)
        
        batch_idx += 1
        
        # Tryb reczny: losowe opoznienie miedzy partiami (3-6 min)
        # Zapobiega wykryciu przez Allegro, celuje w ~8h dla calego raportu
        if fast_mode and not _stop_event.is_set() and batch_idx < len(schedule):
            delay = random.uniform(MANUAL_MIN_BATCH_DELAY, MANUAL_MAX_BATCH_DELAY)  # nosec B311
            logger.info(f"Tryb reczny: czekam {delay/60:.1f} min do nastepnej partii")
            _stop_event.wait(delay)
    
    # Finalizuj raport
    with app.app_context():
        finalize_report(report_id)
        
        # Wyslij powiadomienie po 16:00 w niedziele
        now = datetime.now()
        if now.weekday() == 6:  # Niedziela
            if now.hour >= 16:
                send_report_notification(report_id)
            else:
                # Zaplanuj powiadomienie na 16:00
                wait_until_16 = (now.replace(hour=16, minute=0, second=0) - now).total_seconds()
                if wait_until_16 > 0:
                    logger.info(f"Czekam {wait_until_16/60:.1f} min na wyslanie powiadomienia")
                    time.sleep(wait_until_16)
                send_report_notification(report_id)
        else:
            # Jesli nie niedziela, wyslij od razu
            send_report_notification(report_id)
    
    logger.info(f"Zakonczono przetwarzanie raportu #{report_id}")


def _scheduler_main(app):
    """Glowna petla schedulera."""
    logger.info("Scheduler raportow cenowych uruchomiony")
    
    while not _stop_event.is_set():
        now = datetime.now()
        
        # Sprawdz czy jest piatek 16:00
        if now.weekday() == 4 and now.hour == FRIDAY_START_HOUR:
            # Sprawdz czy nie ma juz uruchomionego raportu
            from .db import get_session
            from .models import PriceReport
            
            with app.app_context():
                with get_session() as session:
                    running = session.query(PriceReport).filter(
                        PriceReport.status.in_(["pending", "running"])
                    ).first()
                    
                    if running:
                        logger.info(f"Raport #{running.id} juz w toku - pomijam")
                    else:
                        # Synchronizuj oferty przed raportem
                        sync_allegro_offers_before_report()
                        
                        # Utworz nowy raport
                        report_id = create_new_report()
                        
                        total_offers = get_active_offers_count()
                        num_batches = (total_offers + BATCH_SIZE - 1) // BATCH_SIZE
                        schedule = [now] * max(num_batches, 1)
                        
                        logger.info(f"Automatyczny raport #{report_id}: {num_batches} partii dla {total_offers} ofert (tryb szybki)")
                        
                        # Uruchom worker w trybie szybkim (identycznie jak recznie)
                        _start_worker(app, report_id, schedule, fast_mode=True)
            
            # Czekaj godzine zeby nie uruchamiac ponownie
            _stop_event.wait(3600)
        else:
            # Sprawdzaj co minute
            _stop_event.wait(60)
    
    logger.info("Scheduler raportow cenowych zatrzymany")


def start_price_report_scheduler(app):
    """Uruchamia scheduler raportow cenowych."""
    global _scheduler_thread
    
    _runtime.start(
        _scheduler_main,
        app,
        already_running_message="Scheduler juz uruchomiony",
        started_message="Uruchomiono scheduler raportow cenowych",
    )
    _scheduler_thread = _runtime.thread


def stop_price_report_scheduler():
    """Zatrzymuje scheduler."""
    global _scheduler_thread
    
    _stop_event.set()
    _runtime.stop(
        stopping_message="Zatrzymywanie schedulera raportow cenowych...",
        stopped_message="Zatrzymano scheduler raportow cenowych",
    )
    _scheduler_thread = None


def start_price_report_now() -> int:
    """Reczne uruchomienie raportu cenowego (poza harmonogramem).
    
    Tryb szybki (fast_mode=True):
    - Wszystkie partie startuja natychmiast (bez czekania na harmonogram)
    - Brak pauzy nocnej
    - Losowe opoznienie 3-6 min miedzy partiami (anti-ban Allegro)
    - Celowal czas: ~8h dla ~400 ofert
    """
    from flask import current_app
    
    # Synchronizuj oferty przed raportem
    sync_allegro_offers_before_report()
    
    # Utworz raport
    report_id = create_new_report()
    
    total_offers = get_active_offers_count()
    num_batches = (total_offers + BATCH_SIZE - 1) // BATCH_SIZE
    
    # Harmonogram: wszystkie partie "od zaraz" - faktyczne opoznienie
    # zarzadza _report_worker przez MANUAL_MIN/MAX_BATCH_DELAY
    now = datetime.now()
    schedule = [now] * max(num_batches, 1)
    
    logger.info(
        f"Reczny raport #{report_id}: {num_batches} partii dla {total_offers} ofert "
        f"(tryb szybki, opoznienie {MANUAL_MIN_BATCH_DELAY//60}-{MANUAL_MAX_BATCH_DELAY//60} min miedzy partiami)"
    )
    
    # Uruchom worker w trybie szybkim
    app = current_app._get_current_object()
    if not _start_worker(app, report_id, schedule, fast_mode=True):
        raise RuntimeError("Worker jest juz aktywny - poczekaj na zakonczenie biezacego raportu")
    
    return report_id


def resume_price_report(report_id: int = None) -> int:
    """Wznawia przetwarzanie istniejacego raportu.
    
    Jesli report_id nie podany, wznawia ostatni raport ze statusem 'running' lub 'pending'.
    """
    from flask import current_app
    from .db import get_session
    from .models import PriceReport, AllegroOffer
    
    with get_session() as session:
        if report_id:
            report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        else:
            # Znajdz ostatni niezakonczony raport
            report = session.query(PriceReport).filter(
                PriceReport.status.in_(["pending", "running"])
            ).order_by(PriceReport.id.desc()).first()
        
        if not report:
            logger.error("Nie znaleziono raportu do wznowienia")
            return None
        
        report_id = report.id
        
        # Ile zostalo do sprawdzenia
        total_active = session.query(AllegroOffer).filter(
            AllegroOffer.publication_status == "ACTIVE"
        ).count()
        
        already_checked = _count_checked_offers(session, report_id)
        
        remaining = total_active - already_checked
        
        # Ustaw status na running
        report.status = "running"
        session.commit()
        
        logger.info(f"Wznawiam raport #{report_id}: {already_checked} sprawdzonych, {remaining} pozostalo")
    
    if remaining <= 0:
        logger.info(f"Raport #{report_id} juz zakonczony - finalizuje")
        finalize_report(report_id)
        return report_id
    
    # Oblicz harmonogram dla pozostalych ofert
    now = datetime.now()
    num_batches = (remaining + BATCH_SIZE - 1) // BATCH_SIZE
    schedule = [now] * max(num_batches, 1)
    
    logger.info(f"Wznowienie raportu #{report_id}: {num_batches} partii dla {remaining} pozostalych ofert (tryb szybki)")
    
    # Uruchom worker
    app = current_app._get_current_object()
    _start_worker(app, report_id, schedule, fast_mode=True)
    
    return report_id


def restart_price_report(report_id: int) -> dict:
    """Restartuje raport - usuwa wpisy z bledami i kontynuuje sprawdzanie.
    
    Returns
    -------
    dict
        Slownik z wynikiem operacji.
    """
    from flask import current_app
    from .db import get_session
    from .models import PriceReport, AllegroOffer, PriceReportItem
    
    with get_session() as session:
        report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        
        if not report:
            return {"success": False, "error": "Nie znaleziono raportu"}
        
        # Usun wpisy z bledami - beda sprawdzone ponownie
        error_items = session.query(PriceReportItem).filter(
            PriceReportItem.report_id == report_id,
            PriceReportItem.error != None
        ).all()
        
        removed_errors = len(error_items)
        for item in error_items:
            session.delete(item)
        
        # Zaktualizuj licznik items_checked
        checked_count = _count_checked_offers(session, report_id)
        report.items_checked = checked_count
        
        # Ile ofert zostalo do sprawdzenia
        total_active = session.query(AllegroOffer).filter(
            AllegroOffer.publication_status == "ACTIVE"
        ).count()
        
        # Zaktualizuj items_total na wypadek gdyby sie zmienila liczba ofert
        report.items_total = total_active
        
        remaining = total_active - checked_count
        
        # Ustaw status na running
        report.status = "running"
        session.commit()
        
        logger.info(f"Restart raportu #{report_id}: usunieto {removed_errors} bledow, {remaining} do sprawdzenia")
    
    if remaining <= 0:
        logger.info(f"Raport #{report_id} nie ma ofert do sprawdzenia - finalizuje")
        finalize_report(report_id)
        return {
            "success": True,
            "removed_errors": removed_errors,
            "remaining": 0,
            "message": "Raport zakonczony - brak ofert do sprawdzenia"
        }
    
    # Oblicz harmonogram
    now = datetime.now()
    num_batches = (remaining + BATCH_SIZE - 1) // BATCH_SIZE
    schedule = [now] * max(num_batches, 1)
    
    logger.info(f"Restart raportu #{report_id}: {num_batches} partii dla {remaining} ofert (tryb szybki)")
    
    # Uruchom worker
    app = current_app._get_current_object()
    _start_worker(app, report_id, schedule, fast_mode=True)
    
    return {
        "success": True,
        "removed_errors": removed_errors,
        "remaining": remaining,
        "message": "Raport zrestartowany"
    }


def auto_resume_incomplete_reports():
    """Automatycznie wznawia niedokonczone raporty przy starcie aplikacji.
    
    Wywolywane przy starcie serwera - sprawdza czy sa raporty w statusie
    'pending' lub 'running' i automatycznie je wznawia.
    
    WYMAGA: app context (musi byc wywolane w 'with app.app_context()')
    """
    from .db import get_session
    from .models import PriceReport
    
    try:
        with get_session() as session:
            incomplete = session.query(PriceReport).filter(
                PriceReport.status.in_(["pending", "running"])
            ).order_by(PriceReport.id.desc()).all()
            
            if not incomplete:
                logger.info("Brak niedokonczonych raportow do wznowienia")
                return
            
            for report in incomplete:
                logger.info(f"Znaleziono niedokonczony raport #{report.id} ({report.items_checked}/{report.items_total})")
                try:
                    resumed_id = resume_price_report(report.id)
                    if resumed_id:
                        logger.info(f"Automatycznie wznowiono raport #{resumed_id}")
                    else:
                        logger.warning(f"Nie udalo sie wznoowic raportu #{report.id}")
                except Exception as e:
                    logger.error(f"Blad wznawiania raportu #{report.id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Blad sprawdzania niedokonczonych raportow: {e}", exc_info=True)