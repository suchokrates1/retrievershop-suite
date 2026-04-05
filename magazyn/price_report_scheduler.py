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


def mark_sibling_offers(report_id: int) -> int:
    """Oznacza oferty z tansza siostra (ten sam product_size_id) jako 'Inna OK'.
    
    Jesli mamy 2+ oferty tego samego product_size_id, ta o nizszej cenie
    wymaga sprawdzenia z konkurencja, a drozsze dostaja wpis bez scrapingu.
    
    Returns
    -------
    int
        Liczba ofert oznaczonych jako 'Inna OK'.
    """
    from .db import get_session
    from .models import AllegroOffer, PriceReportItem, PriceReport

    marked = 0
    with get_session() as session:
        # Znajdz oferty juz sprawdzone w tym raporcie
        checked_offer_ids = set(
            row[0] for row in session.query(PriceReportItem.offer_id).filter(
                PriceReportItem.report_id == report_id
            ).all()
        )

        # Pobierz wszystkie aktywne oferty pogrupowane po product_size_id
        active_offers = session.query(AllegroOffer).filter(
            AllegroOffer.publication_status == "ACTIVE",
            AllegroOffer.product_size_id != None,
        ).all()

        # Grupuj po product_size_id
        groups = {}
        for o in active_offers:
            groups.setdefault(o.product_size_id, []).append(o)

        for ps_id, offers in groups.items():
            if len(offers) < 2:
                continue

            # Posortuj po cenie rosnaco - najtansza wymaga sprawdzenia
            offers_sorted = sorted(offers, key=lambda x: float(x.price) if x.price else 999999)
            cheapest = offers_sorted[0]

            for o in offers_sorted[1:]:
                if o.offer_id in checked_offer_ids:
                    continue

                # Ta oferta jest drozsza od naszej innej - oznacz jako "Inna OK"
                cheapest_price = float(cheapest.price) if cheapest.price else None
                our_price = float(o.price) if o.price else None

                if our_price and cheapest_price and our_price > cheapest_price:
                    item = PriceReportItem(
                        report_id=report_id,
                        offer_id=o.offer_id,
                        product_name=o.title,
                        our_price=Decimal(str(our_price)),
                        competitor_price=None,
                        competitor_seller=None,
                        is_cheapest=False,
                        our_position=None,
                        total_offers=None,
                        error=None,
                    )
                    session.add(item)
                    marked += 1
                    logger.info(
                        f"Inna OK: {o.offer_id} ({our_price} zl) - tansza siostra "
                        f"{cheapest.offer_id} ({cheapest_price} zl) na product_size={ps_id}"
                    )

        if marked > 0:
            # Zaktualizuj postep raportu
            report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
            if report:
                report.items_checked += marked
            session.commit()
            logger.info(f"Oznaczono {marked} ofert jako 'Inna OK' w raporcie #{report_id}")

    return marked


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
        ).scalar_subquery()
        
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
    from .allegro_api.offers import get_offer_badge_price
    
    # Sprawdz cene promocyjna z kampanii (np. Allegro Days) przez API
    badge_price = get_offer_badge_price(offer["offer_id"])
    effective_api_price = float(badge_price) if badge_price else offer["price"]
    
    result = await check_offer_price(
        offer["offer_id"],
        offer["title"],
        effective_api_price,
        cdp_host,
        cdp_port,
        MAX_DELIVERY_DAYS
    )
    
    # Calkowita liczba konkurentow PRZED filtrami
    competitors_all_count = result.competitors_all_count if result.success else 0
    
    # Nasze inne oferty z dialogu (offer_id + cena)
    our_siblings = []
    if result.success and result.our_other_offers:
        our_siblings = [
            {"offer_id": o.offer_id, "price": o.price}
            for o in result.our_other_offers
            if o.offer_id
        ]
    
    return {
        "offer_id": offer["offer_id"],
        "title": offer["title"],
        # Priorytet: cena z kampanii (badge) -> cena bazowa z API
        "our_price": effective_api_price,
        "product_size_id": offer["product_size_id"],
        "success": result.success,
        "error": result.error,
        "my_position": result.my_position,
        "competitors_count": len(result.competitors) if result.competitors else 0,
        "competitors_all_count": competitors_all_count,
        "our_siblings": our_siblings,
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
    from .models import PriceReportItem, PriceReport, AllegroOffer
    
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
        
        # Oznacz siostry z CDP jako "Inna OK"
        # Jesli sprawdzana oferta jest tansza od siostry widocznej w dialogu,
        # siostra nie wymaga osobnego scrapingu - jest drozsza na pewno
        siblings = result.get("our_siblings", [])
        siblings_marked = 0
        if our_price and siblings:
            for sib in siblings:
                sib_id = sib["offer_id"]
                sib_price = sib["price"]

                if sib_id == result["offer_id"]:
                    continue
                if sib_price is None or float(our_price) >= sib_price:
                    continue

                # Siostra jest drozsza - sprawdz czy juz istnieje w raporcie
                existing_sib = session.query(PriceReportItem).filter(
                    PriceReportItem.report_id == report_id,
                    PriceReportItem.offer_id == sib_id,
                ).first()

                if existing_sib:
                    # Siostra juz sprawdzona normalnie - nadpisz na "Inna OK"
                    if existing_sib.competitor_price is not None:
                        existing_sib.competitor_price = None
                        existing_sib.competitor_seller = None
                        existing_sib.is_cheapest = False
                        existing_sib.our_position = None
                        existing_sib.total_offers = None
                        existing_sib.price_difference = None
                        existing_sib.error = None
                        logger.info(
                            f"Inna OK (CDP update): {sib_id} ({sib_price} zl) - tansza siostra "
                            f"{result['offer_id']} ({float(our_price)} zl) wykryta w dialogu"
                        )
                    continue

                # Siostra nie sprawdzona - dodaj nowy item
                sib_offer = session.query(AllegroOffer).filter(
                    AllegroOffer.offer_id == sib_id
                ).first()
                sib_title = sib_offer.title if sib_offer else f"Siostra oferty {result['offer_id']}"

                sib_item = PriceReportItem(
                    report_id=report_id,
                    offer_id=sib_id,
                    product_name=sib_title,
                    our_price=Decimal(str(sib_price)),
                    competitor_price=None,
                    competitor_seller=None,
                    is_cheapest=False,
                    our_position=None,
                    total_offers=None,
                    error=None,
                )
                session.add(sib_item)
                siblings_marked += 1
                logger.info(
                    f"Inna OK (CDP): {sib_id} ({sib_price} zl) - tansza siostra "
                    f"{result['offer_id']} ({float(our_price)} zl) wykryta w dialogu"
                )
        
        # Aktualizuj postep raportu
        report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        if report:
            report.items_checked += 1 + siblings_marked
            report.status = "running"
        
        session.commit()


def finalize_report(report_id: int):
    """Oznacza raport jako zakonczony."""
    from .db import get_session
    from .models import PriceReport, PriceReportItem
    
    with get_session() as session:
        report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        if report:
            error_count = session.query(PriceReportItem).filter(
                PriceReportItem.report_id == report_id,
                PriceReportItem.error != None
            ).count()
            if error_count > 0:
                report.status = "completed_with_errors"
                logger.warning(f"Raport #{report_id} zakonczony z {error_count} bledami - status: completed_with_errors")
            else:
                report.status = "completed"
            report.completed_at = datetime.now()
            session.commit()
            logger.info(f"Raport #{report_id} zakonczony (bledy: {error_count})")


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
        
        # Tryb reczny: losowe opoznienie miedzy partiami (3-6 min)
        # Zapobiega wykryciu przez Allegro, celuje w ~8h dla calego raportu
        if fast_mode and not _stop_event.is_set() and batch_idx < len(schedule):
            delay = random.uniform(MANUAL_MIN_BATCH_DELAY, MANUAL_MAX_BATCH_DELAY)
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