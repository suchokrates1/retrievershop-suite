#!/usr/bin/env python3
"""
Scraper cen konkurencji Allegro przez CDP (Chrome DevTools Protocol).

Laczy sie z uruchomiona przegladarka przez websockets i parsuje dialog
"Inne oferty produktu" z tekstowej zawartosci.

Wymaga:
- Uruchomionego kontenera Chrome na minipc (linuxserver/chromium)
- Zalogowania na Allegro przez VNC
- Pip install websockets

Uzycie lokalne:
    python price_checker_ws.py --offer-id 17895075509

Uzycie na RPI (z baza danych):
    python price_checker_ws.py --check-db --limit 10
"""

import asyncio
import json
import argparse
import re
import sys
import logging
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, asdict
from decimal import Decimal
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Zainstaluj: pip install websockets")
    sys.exit(1)

import urllib.request
import urllib.parse

# Dodaj katalog magazyn do sciezki
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Konfiguracja
CDP_HOST = "192.168.31.147"  # minipc
CDP_PORT = 9223
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 4  # Filtruj sprzedawcow z dluga dostawa (chinczycy)

# Polskie miesiace do parsowania daty dostawy
POLISH_MONTHS = {
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9, "paz": 10, "lis": 11, "gru": 12
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class CompetitorOffer:
    """Reprezentuje oferte konkurencji."""
    seller: str
    price: float
    price_with_delivery: float
    is_mine: bool = False
    delivery_days: Optional[int] = None
    delivery_text: str = ""
    offer_url: str = ""


@dataclass
class PriceCheckResult:
    """Wynik sprawdzenia cen dla oferty."""
    offer_id: str
    success: bool
    my_price: Optional[float] = None
    competitors: List[CompetitorOffer] = None
    cheapest_competitor: Optional[CompetitorOffer] = None
    my_position: int = 0
    error: Optional[str] = None
    checked_at: str = ""
    
    def __post_init__(self):
        if self.competitors is None:
            self.competitors = []
        if not self.checked_at:
            self.checked_at = datetime.now().isoformat()


def parse_price(price_str: str) -> float:
    """Parsuje cene z formatu '206,00' do float."""
    return float(price_str.replace(",", ".").replace(" ", ""))


def parse_delivery_days(text: str) -> Optional[int]:
    """Parsuje tekst dostawy na liczbe dni.
    
    Rozpoznaje formaty:
    - 'dostawa w sobote' -> oblicza dni do soboty
    - 'dostawa za 2-3 dni' -> srednia (2)
    - '5 lut' -> dni do 5 lutego
    - 'jutro' -> 1
    - 'dzisiaj' -> 0
    """
    if not text:
        return None
    t = text.lower().strip()
    
    # 'dostawa od X' - pomijamy (nieznana data, czesto chinczycy)
    if re.match(r"^dostawa\s+od\s+\d", t):
        return 99  # Wysoka wartosc = odfiltruj
    
    # 'dostawa za X-Y dni'
    m = re.search(r"dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni", t)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    
    # 'dostawa za X dni'
    m = re.search(r"dostawa\s+za\s+(\d+)\s*dni", t)
    if m:
        return int(m.group(1))
    
    # 'X sty' - konkretna data (np. '5 lut')
    m = re.search(r"(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paz|lis|gru)", t)
    if m:
        day, month = int(m.group(1)), POLISH_MONTHS.get(m.group(2), 1)
        today = datetime.now()
        try:
            target = datetime(today.year, month, day)
            if target < today:
                target = datetime(today.year + 1, month, day)
            return (target - today).days
        except:
            pass
    
    # Dni tygodnia - z polskimi znakami i bez
    days_of_week = {
        "poniedzialek": 0, "poniedziałek": 0, "poniedział": 0,
        "wtorek": 1, "wtor": 1,
        "sroda": 2, "środa": 2, "srod": 2, "środ": 2,
        "czwartek": 3, "czwart": 3,
        "piatek": 4, "piątek": 4, "piąt": 4, "piat": 4,
        "sobota": 5, "sobot": 5, "sobo": 5,
        "niedziela": 6, "niedziel": 6, "niedz": 6
    }
    for day_name, day_num in days_of_week.items():
        if day_name in t:
            today = datetime.now()
            today_weekday = today.weekday()
            days_ahead = day_num - today_weekday
            if days_ahead <= 0:
                days_ahead += 7
            return days_ahead
    
    if "jutro" in t:
        return 1
    if "dzisiaj" in t or "dzis" in t or "dziś" in t:
        return 0
    
    return None


def build_offer_url(offer_id: str, title: str = "") -> str:
    """Buduje URL oferty z fragmentem #inne-oferty-produktu."""
    if title:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
        return f"https://allegro.pl/oferta/{slug}-{offer_id}#inne-oferty-produktu"
    return f"https://allegro.pl/oferta/x-{offer_id}#inne-oferty-produktu"


async def get_cdp_websocket_url(host: str = CDP_HOST, port: int = CDP_PORT) -> str:
    """Pobiera URL WebSocket dla glownej strony z CDP."""
    url = f"http://{host}:{port}/json"
    
    def fetch():
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    
    loop = asyncio.get_event_loop()
    pages = await loop.run_in_executor(None, fetch)
    
    # Znajdz glowna strone (nie devtools)
    for page in pages:
        if page.get("type") == "page" and "devtools" not in page.get("url", "").lower():
            return page["webSocketDebuggerUrl"]
    
    raise RuntimeError("Nie znaleziono strony w CDP")


async def cdp_call(ws, method: str, params: dict = None, msg_id: int = 1) -> dict:
    """Wykonuje wywolanie CDP i zwraca wynik."""
    request = {"id": msg_id, "method": method}
    if params:
        request["params"] = params
    
    await ws.send(json.dumps(request))
    
    while True:
        resp = await ws.recv()
        data = json.loads(resp)
        if data.get("id") == msg_id:
            return data
        # Ignoruj eventy


async def navigate_to_url(ws, url: str, timeout: int = 30):
    """Nawiguje do podanego URL i czeka na zaladowanie."""
    logger.info(f"Nawiguje do: {url[:80]}...")
    
    # Wlacz eventy Page
    await cdp_call(ws, "Page.enable", msg_id=1)
    
    # Nawiguj
    await cdp_call(ws, "Page.navigate", {"url": url}, msg_id=2)
    
    # Czekaj na zaladowanie
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=1)
            data = json.loads(msg)
            if data.get("method") == "Page.loadEventFired":
                logger.debug("Strona zaladowana")
                break
        except asyncio.TimeoutError:
            continue
    
    # Dodatkowe opoznienie na JS
    await asyncio.sleep(3)


async def wait_for_dialog(ws, timeout: int = 15) -> bool:
    """Czeka az pojawi sie dialog z ofertami."""
    js_check = '''
    (function() {
        const dialogs = document.querySelectorAll("[role='dialog']");
        for (const d of dialogs) {
            if (d.innerText?.includes("Inne oferty produktu")) {
                return true;
            }
        }
        return false;
    })()
    '''
    
    msg_id = 100
    start = asyncio.get_event_loop().time()
    
    while asyncio.get_event_loop().time() - start < timeout:
        result = await cdp_call(ws, "Runtime.evaluate", 
                                {"expression": js_check, "returnByValue": True}, 
                                msg_id=msg_id)
        msg_id += 1
        
        if result.get("result", {}).get("result", {}).get("value"):
            logger.debug("Dialog znaleziony")
            return True
        
        await asyncio.sleep(1)
    
    return False


async def extract_competitor_offers(ws, product_title: str = "") -> List[CompetitorOffer]:
    """Wyciaga oferty konkurencji z dialogu.
    
    Parsuje kazdy kafelek (article) osobno, wyciagajac z niego:
    - offerId z linku w tytule (href zawiera ?offerId=XXX)
    - tekst z cenami, sprzedawca, dostawa
    
    Dzieki temu dane sa prawidlowo powiazane (bez mieszania linkow).
    """
    # JavaScript ktory parsuje kazdy article osobno i wyciaga wszystkie dane
    js_code = r'''
    (function() {
        const container = document.querySelector('[data-box-name="ProductOffersListingContainer"]');
        if (!container) {
            // Fallback - szukaj w dialogu
            const dialogs = document.querySelectorAll("[role='dialog']");
            for (const d of dialogs) {
                if (d.innerText?.includes("Inne oferty produktu")) {
                    const c = d.querySelector('[data-box-name="ProductOffersListingContainer"]');
                    if (c) {
                        container = c;
                        break;
                    }
                }
            }
        }
        if (!container) return [];
        
        const articles = container.querySelectorAll('article');
        
        return Array.from(articles).map((art, idx) => {
            // Link do oferty - moze byc w /produkt/?offerId= lub /events/clicks?redirect=
            let offerId = null;
            
            // 1. Szukaj linku /produkt/?offerId=
            const produktLink = art.querySelector('a[href*="/produkt/"]');
            if (produktLink) {
                const match = produktLink.href.match(/offerId=(\d+)/);
                if (match) offerId = match[1];
            }
            
            // 2. Fallback: link /events/clicks z redirect do oferty
            if (!offerId) {
                const eventLink = art.querySelector('a[href*="/events/clicks"]');
                if (eventLink) {
                    // URL jest zakodowany w redirect= parametrze
                    const redirectMatch = eventLink.href.match(/redirect=([^&]+)/);
                    if (redirectMatch) {
                        const decoded = decodeURIComponent(redirectMatch[1]);
                        const offerMatch = decoded.match(/-(\d{10,})/);  // ID oferty w URL
                        if (offerMatch) offerId = offerMatch[1];
                    }
                }
            }
            
            return {
                index: idx,
                offerId: offerId,
                text: art.innerText || ''
            };
        });
    })()
    '''
    
    result = await cdp_call(ws, "Runtime.evaluate", 
                            {"expression": js_code, "returnByValue": True}, 
                            msg_id=200)
    
    articles = result.get("result", {}).get("result", {}).get("value", [])
    
    if not articles:
        logger.warning("Nie znaleziono artykulow w dialogu")
        return []
    
    logger.debug(f"Znaleziono {len(articles)} artykulow")
    
    offers = []
    for art in articles:
        text = art.get("text", "")
        offer_id = art.get("offerId")
        
        # Sprzedawca - dwa wzorce:
        # 1. "| \n sprzedawca" - normalne oferty konkurencji
        # 2. "od \n Super Sprzedawcy? \n | \n sprzedawca" LUB "od \n sprzedawca" - bez "|"
        seller_match = re.search(r'\|\s*\n\s*(\S+)', text)
        if not seller_match:
            # Fallback: szukaj po "od" (dla ofert bez "|", np. moja oferta)
            seller_match = re.search(r'\bod\s*\n(?:Super Sprzedawcy\s*\n)?\s*(\S+)', text)
        
        # Cena glowna
        price_match = re.search(r'(\d+(?:,\d{2})?)\s*zł\s*\n', text)
        # Cena z dostawa
        delivery_match = re.search(r'(\d+(?:,\d{2})?)\s*zł\s*z\s*dostaw', text)
        # Tekst dostawy (np. "dostawa w sobote", "dostawa za 2-3 dni")
        delivery_text_match = re.search(r'(dostawa\s+(?:w\s+\w+|za\s+\d+.*?dni|od\s+\d+))', text, re.IGNORECASE)
        # Czy to moja oferta? - sprawdz TYLKO nazwe sprzedawcy (nie "Top oferta" bo moze byc u konkurencji)
        seller = seller_match.group(1) if seller_match else "nieznany"
        is_mine = seller.lower() == MY_SELLER.lower()
        
        if price_match:
            price = parse_price(price_match.group(1))
            total = parse_price(delivery_match.group(1)) if delivery_match else price
            delivery_text = delivery_text_match.group(1) if delivery_text_match else ""
            delivery_days = parse_delivery_days(delivery_text)
            
            # Buduj URL oferty
            offer_url = ""
            if offer_id:
                offer_url = f"https://allegro.pl/oferta/x-{offer_id}"
            elif seller and seller != "nieznany" and product_title:
                # Fallback: URL wyszukiwania z loginem sprzedawcy
                search_query = urllib.parse.quote(product_title[:50])
                offer_url = f"https://allegro.pl/listing?string={search_query}&sellerLogin={seller}"
            
            offers.append(CompetitorOffer(
                seller=seller,
                price=price,
                price_with_delivery=total,
                is_mine=is_mine,
                delivery_days=delivery_days,
                delivery_text=delivery_text,
                offer_url=offer_url
            ))
    
    return offers


async def check_offer_price(
    offer_id: str, 
    title: str = "", 
    my_price: float = None,
    cdp_host: str = CDP_HOST,
    cdp_port: int = CDP_PORT,
    max_delivery_days: int = MAX_DELIVERY_DAYS
) -> PriceCheckResult:
    """Sprawdza ceny konkurencji dla danej oferty.
    
    Args:
        offer_id: ID oferty Allegro
        title: Tytul oferty (opcjonalny, do budowania URL)
        my_price: Nasza cena (opcjonalna)
        cdp_host: Host CDP
        cdp_port: Port CDP
        max_delivery_days: Maksymalna liczba dni dostawy (filtruje chinskich sprzedawcow)
    """
    
    result = PriceCheckResult(
        offer_id=offer_id,
        success=False,
        my_price=my_price,
    )
    
    url = build_offer_url(offer_id, title)
    
    try:
        ws_url = await get_cdp_websocket_url(cdp_host, cdp_port)
        logger.debug(f"CDP WebSocket: {ws_url}")
        
        async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
            # Nawiguj do oferty
            await navigate_to_url(ws, url)
            
            # Czekaj na dialog
            if not await wait_for_dialog(ws):
                result.error = "Dialog 'Inne oferty produktu' nie pojawil sie"
                return result
            
            # Wyciagnij oferty
            all_offers = await extract_competitor_offers(ws, title)
            
            if not all_offers:
                result.error = "Brak ofert w dialogu"
                return result
            
            # Znajdz moja oferte
            my_offer = next((o for o in all_offers if o.is_mine), None)
            if my_offer and not result.my_price:
                result.my_price = my_offer.price
            
            # Filtruj konkurencje po czasie dostawy (bez mojej oferty)
            competitors_all = [o for o in all_offers if not o.is_mine]
            competitors_filtered = [
                o for o in competitors_all
                if o.delivery_days is None or o.delivery_days <= max_delivery_days
            ]
            
            # Loguj odfiltrowanych
            filtered_count = len(competitors_all) - len(competitors_filtered)
            if filtered_count > 0:
                logger.info(f"Odfiltrowano {filtered_count} ofert z dostawa > {max_delivery_days} dni")
            
            result.competitors = competitors_filtered
            
            # Najtanszy konkurent (tylko z szybka dostawa)
            if competitors_filtered:
                result.cheapest_competitor = min(competitors_filtered, key=lambda x: x.price_with_delivery)
            
            # Moja pozycja (tylko wsrod ofert z szybka dostawa)
            offers_for_ranking = [o for o in all_offers if o.is_mine or (o.delivery_days is None or o.delivery_days <= max_delivery_days)]
            sorted_offers = sorted(offers_for_ranking, key=lambda x: x.price_with_delivery)
            for i, o in enumerate(sorted_offers, 1):
                if o.is_mine:
                    result.my_position = i
                    break
            
            result.success = True
            
    except Exception as e:
        logger.error(f"Blad podczas sprawdzania oferty {offer_id}: {e}")
        result.error = str(e)
    
    return result


def print_result(result: PriceCheckResult):
    """Wyswietla wynik sprawdzenia."""
    print(f"\n=== Oferta {result.offer_id} ===")
    print(f"Czas: {result.checked_at}")
    
    if not result.success:
        print(f"BLAD: {result.error}")
        return
    
    if result.my_price:
        print(f"Moja cena: {result.my_price:.2f} zl")
        total_offers = len(result.competitors) + 1
        print(f"Moja pozycja: {result.my_position}/{total_offers}")
    
    print(f"\nKonkurenci ({len(result.competitors)}):")
    for i, c in enumerate(result.competitors, 1):
        # Wyswietl czas dostawy jesli znany
        days_str = f" [{c.delivery_days}d]" if c.delivery_days is not None else ""
        print(f"  {i}. {c.seller}: {c.price:.2f} zl ({c.price_with_delivery:.2f} zl z dostawa){days_str}")
    
    if result.cheapest_competitor:
        c = result.cheapest_competitor
        days_info = f" (dostawa {c.delivery_days}d)" if c.delivery_days is not None else ""
        print(f"\nNajtansza konkurencja: {c.seller} - {c.price_with_delivery:.2f} zl z dostawa{days_info}")
        if c.offer_url:
            print(f"Link: {c.offer_url}")
        
        if result.my_price:
            diff = result.my_price - c.price
            if diff > 0:
                print(f"Jestem DROZSZY o {diff:.2f} zl")
            elif diff < 0:
                print(f"Jestem TANSZY o {-diff:.2f} zl")
            else:
                print("Mam taka sama cene")


async def check_offers_from_db(cdp_host: str, cdp_port: int, limit: int = 10, max_delivery_days: int = MAX_DELIVERY_DAYS):
    """Sprawdza oferty z bazy danych."""
    
    try:
        from magazyn.config import settings
        from magazyn.models import AllegroOffer, AllegroPriceHistory
        from magazyn.db import get_session, configure_engine
        
        # Inicjalizuj polaczenie z baza danych
        configure_engine(settings.DB_PATH)
    except ImportError as e:
        logger.error(f"Nie mozna zaimportowac modulow magazyn: {e}")
        logger.error("Uruchom z katalogu retrievershop-suite lub ustaw PYTHONPATH")
        return
    
    with get_session() as session:
        offers = session.query(AllegroOffer).filter(
            AllegroOffer.publication_status == "ACTIVE"
        ).limit(limit).all()
        
        logger.info(f"Znaleziono {len(offers)} aktywnych ofert (filtr dostawy: max {max_delivery_days} dni)")
        
        for i, offer in enumerate(offers, 1):
            print(f"\n[{i}/{len(offers)}] {offer.title[:50]}...")
            
            result = await check_offer_price(
                offer.offer_id,
                offer.title,
                float(offer.price) if offer.price else None,
                cdp_host,
                cdp_port,
                max_delivery_days
            )
            
            print_result(result)
            
            if result.success and result.cheapest_competitor:
                # Zapisz do historii
                history = AllegroPriceHistory(
                    offer_id=offer.offer_id,
                    product_size_id=offer.product_size_id,
                    price=offer.price,
                    recorded_at=datetime.now().isoformat(),
                    competitor_price=Decimal(str(result.cheapest_competitor.price)),
                    competitor_seller=result.cheapest_competitor.seller,
                    competitor_delivery_days=result.cheapest_competitor.delivery_days,
                    competitor_url=result.cheapest_competitor.offer_url or None,
                )
                session.add(history)
                logger.info(f"Zapisano do historii: {result.cheapest_competitor.seller} @ {result.cheapest_competitor.price}")
            
            # Opoznienie miedzy zapytaniami
            await asyncio.sleep(3)
        
        session.commit()
        logger.info("Zapisano wszystkie wyniki do bazy")


async def main():
    parser = argparse.ArgumentParser(description="Scraper cen konkurencji Allegro przez CDP")
    parser.add_argument("--offer-id", help="ID oferty do sprawdzenia")
    parser.add_argument("--title", default="", help="Tytul oferty (opcjonalny)")
    parser.add_argument("--my-price", type=float, help="Moja cena (opcjonalna)")
    parser.add_argument("--check-db", action="store_true", help="Sprawdz oferty z bazy danych")
    parser.add_argument("--limit", type=int, default=10, help="Limit ofert przy --check-db")
    parser.add_argument("--cdp-host", default=CDP_HOST, help="Host CDP")
    parser.add_argument("--cdp-port", type=int, default=CDP_PORT, help="Port CDP")
    parser.add_argument("--max-delivery-days", type=int, default=MAX_DELIVERY_DAYS, 
                        help=f"Maksymalna liczba dni dostawy (domyslnie {MAX_DELIVERY_DAYS}, filtruje chinskich sprzedawcow)")
    parser.add_argument("--json", action="store_true", help="Wyswietl wynik jako JSON")
    
    args = parser.parse_args()
    
    if args.offer_id:
        result = await check_offer_price(
            args.offer_id, 
            args.title, 
            args.my_price,
            args.cdp_host,
            args.cdp_port,
            args.max_delivery_days
        )
        
        if args.json:
            print(json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str))
        else:
            print_result(result)
    
    elif args.check_db:
        await check_offers_from_db(args.cdp_host, args.cdp_port, args.limit, args.max_delivery_days)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
