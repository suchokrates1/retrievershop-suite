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
from typing import Optional, List, Tuple
from decimal import Decimal

logger = logging.getLogger(__name__)

_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_current_report_id: Optional[int] = None


# Konfiguracja czasowa
FRIDAY_START_HOUR = 16  # Piatek 16:00
SUNDAY_END_HOUR = 16    # Niedziela 16:00
NIGHT_PAUSE_START = 2   # Przerwa nocna od 02:00
NIGHT_PAUSE_END = 6     # Przerwa nocna do 06:00
BATCH_SIZE = 5          # Ofert w partii
MIN_BATCH_DELAY = 30 * 60    # Min 30 min miedzy partiami
MAX_BATCH_DELAY = 90 * 60    # Max 90 min miedzy partiami


def is_night_pause() -> bool:
    """Sprawdza czy jest przerwa nocna."""
    hour = datetime.now().hour
    return NIGHT_PAUSE_START <= hour < NIGHT_PAUSE_END


def calculate_schedule(total_offers: int, start_time: datetime, end_time: datetime) -> List[datetime]:
    """
    Oblicza harmonogram sprawdzania ofert.
    
    Rozklada oferty rownomiernie z losowymi odchyleniami,
    pomijajac przerwy nocne.
    """
    if total_offers <= 0:
        return []
    
    # Oblicz dostepny czas (pomijajac przerwy nocne)
    available_slots = []
    current = start_time
    
    while current < end_time:
        hour = current.hour
        # Pomin przerwy nocne
        if not (NIGHT_PAUSE_START <= hour < NIGHT_PAUSE_END):
            available_slots.append(current)
        current += timedelta(minutes=15)  # Granulacja 15 min
    
    if not available_slots:
        return []
    
    # Ile partii potrzebujemy
    num_batches = (total_offers + BATCH_SIZE - 1) // BATCH_SIZE
    
    if num_batches >= len(available_slots):
        # Wiecej partii niz slotow - uzyj wszystkich slotow
        schedule = available_slots[:num_batches]
    else:
        # Rozloz rownomiernie z losowoscia
        step = len(available_slots) / num_batches
        schedule = []
        for i in range(num_batches):
            base_idx = int(i * step)
            # Dodaj losowe odchylenie (-2 do +2 slotow, czyli +/- 30 min)
            jitter = random.randint(-2, 2)
            idx = max(0, min(len(available_slots) - 1, base_idx + jitter))
            schedule.append(available_slots[idx])
    
    # Dodaj losowe minuty do kazdego slotu
    final_schedule = []
    for slot in schedule:
        jitter_minutes = random.randint(0, 14)
        final_schedule.append(slot + timedelta(minutes=jitter_minutes))
    
    return sorted(final_schedule)


def get_active_offers_count() -> int:
    """Pobiera liczbe aktywnych ofert Allegro."""
    try:
        from .db import get_session
        from .models import AllegroOffer
        
        with get_session() as session:
            return session.query(AllegroOffer).filter(
                AllegroOffer.publication_status == "ACTIVE"
            ).count()
    except Exception as e:
        logger.error(f"Blad pobierania liczby ofert: {e}")
        return 0


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


def create_new_report() -> int:
    """Tworzy nowy raport cenowy w bazie."""
    from .db import get_session
    from .models import PriceReport, AllegroOffer
    
    with get_session() as session:
        total_offers = session.query(AllegroOffer).filter(
            AllegroOffer.publication_status == "ACTIVE"
        ).count()
        
        report = PriceReport(
            status="pending",
            items_total=total_offers,
            items_checked=0,
        )
        session.add(report)
        session.commit()
        
        logger.info(f"Utworzono raport #{report.id} dla {total_offers} ofert")
        return report.id


def get_unchecked_offers(report_id: int, limit: int = BATCH_SIZE) -> List[dict]:
    """Pobiera oferty do sprawdzenia (jeszcze nie sprawdzone w tym raporcie).
    
    Przed zwroceniem aktualizuje ceny ofert z API Allegro aby miec najnowsze dane.
    """
    from .db import get_session
    from .models import AllegroOffer, PriceReportItem
    from .allegro_api.offers import get_offer_details
    
    with get_session() as session:
        # Znajdz oferty ktore nie maja jeszcze wpisu w tym raporcie
        checked_offer_ids = session.query(PriceReportItem.offer_id).filter(
            PriceReportItem.report_id == report_id
        ).subquery()
        
        offers = session.query(AllegroOffer).filter(
            AllegroOffer.publication_status == "ACTIVE",
            ~AllegroOffer.offer_id.in_(checked_offer_ids)
        ).limit(limit).all()
        
        # Aktualizuj ceny z API Allegro przed sprawdzaniem
        result_offers = []
        for o in offers:
            current_price = float(o.price) if o.price else None
            
            # Pobierz aktualna cene z API
            try:
                offer_details = get_offer_details(o.offer_id)
                if offer_details.get("success") and offer_details.get("price"):
                    new_price = offer_details["price"]
                    # Aktualizuj w bazie jezeli sie zmienila
                    if new_price != o.price:
                        logger.info(f"Aktualizacja ceny oferty {o.offer_id}: {o.price} -> {new_price}")
                        o.price = new_price
                        session.commit()
                        current_price = float(new_price)
            except Exception as e:
                logger.warning(f"Nie udalo sie zaktualizowac ceny oferty {o.offer_id}: {e}")
            
            result_offers.append({
                "offer_id": o.offer_id,
                "title": o.title,
                "price": current_price,
                "product_size_id": o.product_size_id,
            })
        
        return result_offers


async def check_single_offer(offer: dict, cdp_host: str, cdp_port: int) -> dict:
    """Sprawdza pojedyncza oferte przez CDP."""
    from .scripts.price_checker_ws import check_offer_price, MAX_DELIVERY_DAYS
    
    result = await check_offer_price(
        offer["offer_id"],
        offer["title"],
        offer["price"],
        cdp_host,
        cdp_port,
        MAX_DELIVERY_DAYS
    )
    
    # Calkowita liczba konkurentow PRZED filtrami
    competitors_all_count = result.competitors_all_count if result.success else 0
    
    return {
        "offer_id": offer["offer_id"],
        "title": offer["title"],
        # Uzywaj ceny z dialogu (result.my_price) zamiast ceny z bazy (offer["price"])
        # Zapewnia spojnosc miedzy pozycja (liczona z dialogu) a is_cheapest
        "our_price": result.my_price if result.my_price else offer["price"],
        "product_size_id": offer["product_size_id"],
        "success": result.success,
        "error": result.error,
        "my_position": result.my_position,
        "competitors_count": len(result.competitors) if result.competitors else 0,
        "competitors_all_count": competitors_all_count,
        "cheapest": {
            "price": result.cheapest_competitor.price,
            "price_with_delivery": result.cheapest_competitor.price_with_delivery,
            "seller": result.cheapest_competitor.seller,
            "url": result.cheapest_competitor.offer_url,
            "is_super_seller": result.cheapest_competitor.is_super_seller,
        } if result.cheapest_competitor else None,
    }


def save_report_item(report_id: int, result: dict):
    """Zapisuje wynik sprawdzenia oferty do raportu."""
    from .db import get_session
    from .models import PriceReportItem, PriceReport
    
    with get_session() as session:
        our_price = Decimal(str(result["our_price"])) if result["our_price"] else None
        competitor_price = None
        competitor_seller = None
        competitor_url = None
        is_cheapest = True
        price_difference = None
        
        # Dane o najtanszym konkurencie
        competitor_is_super = None
        if result["cheapest"]:
            competitor_price = Decimal(str(result["cheapest"]["price"]))
            competitor_seller = result["cheapest"]["seller"]
            competitor_url = result["cheapest"]["url"]
            competitor_is_super = result["cheapest"].get("is_super_seller", False)
            
            if our_price:
                # Porownujemy po cenie bazowej (wszyscy maja Smart)
                is_cheapest = our_price <= competitor_price
                price_difference = float(our_price - competitor_price)
        
        item = PriceReportItem(
            report_id=report_id,
            offer_id=result["offer_id"],
            product_name=result["title"],
            our_price=our_price,
            competitor_price=competitor_price,
            competitor_seller=competitor_seller,
            competitor_url=competitor_url,
            is_cheapest=is_cheapest,
            price_difference=price_difference,
            our_position=result["my_position"],
            total_offers=result["competitors_count"] + 1,
            competitors_all_count=result.get("competitors_all_count"),
            competitor_is_super_seller=competitor_is_super,
            error=result["error"],
        )
        session.add(item)
        
        # Aktualizuj postep raportu
        report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        if report:
            report.items_checked += 1
            report.status = "running"
        
        session.commit()


def finalize_report(report_id: int):
    """Oznacza raport jako zakonczony."""
    from .db import get_session
    from .models import PriceReport
    
    with get_session() as session:
        report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        if report:
            report.status = "completed"
            report.completed_at = datetime.now()
            session.commit()
            logger.info(f"Raport #{report_id} zakonczony")


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
            
            total = session.query(PriceReportItem).filter(
                PriceReportItem.report_id == report_id
            ).count()
            
            cheapest = session.query(PriceReportItem).filter(
                PriceReportItem.report_id == report_id,
                PriceReportItem.is_cheapest == True
            ).count()
            
            not_cheapest = total - cheapest
        
        # Pobierz konfiguracje Messenger
        access_token = settings_store.get("MESSENGER_ACCESS_TOKEN", "")
        recipient_id = settings_store.get("MESSENGER_RECIPIENT_ID", "")
        
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


def _report_worker(app, report_id: int, schedule: List[datetime]):
    """Worker przetwarzajacy raport."""
    import asyncio
    from .scripts.price_checker_ws import CDP_HOST, CDP_PORT
    
    logger.info(f"Rozpoczynam przetwarzanie raportu #{report_id}, {len(schedule)} partii")
    
    batch_idx = 0
    
    while not _stop_event.is_set() and batch_idx < len(schedule):
        # Czekaj na zaplanowany czas
        target_time = schedule[batch_idx]
        now = datetime.now()
        
        if now < target_time:
            wait_seconds = (target_time - now).total_seconds()
            logger.info(f"Czekam {wait_seconds/60:.1f} min do partii {batch_idx + 1}")
            
            # Czekaj z mozliwoscia przerwania
            if _stop_event.wait(wait_seconds):
                logger.info("Przerwano oczekiwanie")
                break
        
        # Sprawdz czy nie jest przerwa nocna
        if is_night_pause():
            logger.info("Przerwa nocna - czekam do 06:00")
            # Oblicz czas do 06:00
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
                        time.sleep(random.uniform(2, 5))
                        
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
                        
                        # Oblicz harmonogram
                        start_time = now
                        end_time = now + timedelta(days=2)  # Do niedzieli 16:00
                        
                        total_offers = get_active_offers_count()
                        schedule = calculate_schedule(total_offers, start_time, end_time)
                        
                        logger.info(f"Zaplanowano {len(schedule)} partii dla {total_offers} ofert")
                        
                        # Uruchom worker w osobnym watku
                        worker = threading.Thread(
                            target=_report_worker,
                            args=(app, report_id, schedule),
                            daemon=True,
                            name=f"PriceReportWorker-{report_id}"
                        )
                        worker.start()
            
            # Czekaj godzine zeby nie uruchamiac ponownie
            _stop_event.wait(3600)
        else:
            # Sprawdzaj co minute
            _stop_event.wait(60)
    
    logger.info("Scheduler raportow cenowych zatrzymany")


def start_price_report_scheduler(app):
    """Uruchamia scheduler raportow cenowych."""
    global _scheduler_thread
    
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        logger.warning("Scheduler juz uruchomiony")
        return
    
    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_main,
        args=(app,),
        daemon=True,
        name="PriceReportScheduler"
    )
    _scheduler_thread.start()
    logger.info("Uruchomiono scheduler raportow cenowych")


def stop_price_report_scheduler():
    """Zatrzymuje scheduler."""
    global _scheduler_thread
    
    _stop_event.set()
    
    if _scheduler_thread is not None:
        _scheduler_thread.join(timeout=5)
        _scheduler_thread = None
    
    logger.info("Zatrzymano scheduler raportow cenowych")


def start_price_report_now() -> int:
    """Reczne uruchomienie raportu cenowego (poza harmonogramem).
    
    Dla recznego uruchomienia:
    - Synchronizacja ofert z Allegro
    - Pierwsza partia startuje natychmiast
    - Pozostale partie rozlozone rownomiernie na 48h z losowoscia
    """
    from flask import current_app
    
    # Synchronizuj oferty przed raportem
    sync_allegro_offers_before_report()
    
    # Utworz raport
    report_id = create_new_report()
    
    total_offers = get_active_offers_count()
    num_batches = (total_offers + BATCH_SIZE - 1) // BATCH_SIZE
    
    now = datetime.now()
    end_time = now + timedelta(hours=48)
    
    # Oblicz harmonogram dla pozostalych partii (bez pierwszej)
    remaining_schedule = calculate_schedule(
        total_offers - BATCH_SIZE,  # Pomijamy pierwsza partie
        now + timedelta(minutes=5),  # Zaczynamy 5 min od teraz
        end_time
    )
    
    # Pierwsza partia od razu, reszta wedlug harmonogramu
    schedule = [now] + remaining_schedule
    
    logger.info(f"Reczny raport #{report_id}: {len(schedule)} partii dla {total_offers} ofert (pierwsza natychmiast, reszta na 48h)")
    
    # Uruchom worker
    app = current_app._get_current_object()
    worker = threading.Thread(
        target=_report_worker,
        args=(app, report_id, schedule),
        daemon=True,
        name=f"PriceReportWorker-{report_id}"
    )
    worker.start()
    
    return report_id


def resume_price_report(report_id: int = None) -> int:
    """Wznawia przetwarzanie istniejacego raportu.
    
    Jesli report_id nie podany, wznawia ostatni raport ze statusem 'running' lub 'pending'.
    """
    from flask import current_app
    from .db import get_session
    from .models import PriceReport, AllegroOffer, PriceReportItem
    
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
        
        already_checked = session.query(PriceReportItem).filter(
            PriceReportItem.report_id == report_id
        ).count()
        
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
    end_time = now + timedelta(hours=24)  # 24h na dokonczenie
    
    schedule = calculate_schedule(remaining, now, end_time)
    
    logger.info(f"Wznowienie raportu #{report_id}: {len(schedule)} partii dla {remaining} pozostalych ofert")
    
    # Uruchom worker
    app = current_app._get_current_object()
    worker = threading.Thread(
        target=_report_worker,
        args=(app, report_id, schedule),
        daemon=True,
        name=f"PriceReportWorker-{report_id}"
    )
    worker.start()
    
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
        checked_count = session.query(PriceReportItem).filter(
            PriceReportItem.report_id == report_id
        ).count()
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
    
    # Oblicz harmonogram - szybszy dla restartu (6h zamiast 24h)
    now = datetime.now()
    end_time = now + timedelta(hours=6)
    
    schedule = calculate_schedule(remaining, now, end_time)
    
    # Pierwsza partia natychmiast
    if schedule:
        schedule[0] = now
    
    logger.info(f"Restart raportu #{report_id}: {len(schedule)} partii dla {remaining} ofert (pierwsza natychmiast)")
    
    # Uruchom worker
    app = current_app._get_current_object()
    worker = threading.Thread(
        target=_report_worker,
        args=(app, report_id, schedule),
        daemon=True,
        name=f"PriceReportWorker-{report_id}"
    )
    worker.start()
    
    return {
        "success": True,
        "removed_errors": removed_errors,
        "remaining": remaining,
        "message": f"Raport zrestartowany"
    }


def auto_resume_incomplete_reports():
    """Automatycznie wznawia niedokonczone raporty przy starcie aplikacji.
    
    Wywolywane przy starcie serwera - sprawdza czy sa raporty w statusie
    'pending' lub 'running' i automatycznie je wznawia.
    
    WYMAGA: app context (musi byc wywolane w 'with app.app_context()')
    """
    from .db import get_session
    from .models import PriceReport
    from flask import current_app
    
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