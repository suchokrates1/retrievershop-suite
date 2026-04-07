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
from datetime import datetime, date, timedelta
from typing import Optional, List
from dataclasses import dataclass, asdict
from decimal import Decimal
from pathlib import Path

try:
    import websockets
except ImportError:
    websockets = None
    logging.getLogger(__name__).warning("Brak pakietu websockets - scraping CDP niedostepny")

import urllib.request
import urllib.parse
import os

# Dodaj katalog magazyn do sciezki
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Konfiguracja
# Chrome DevTools wymaga IP lub localhost w Host header - hostname (np. "price-checker-chrome")
# powoduje HTTP 500: "Host header is specified and is not an IP address or localhost."
CDP_HOST = os.environ.get("CDP_HOST", "192.168.31.5")  # minipc
CDP_PORT = int(os.environ.get("CDP_PORT", "9223"))
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 3  # Filtruj sprzedawcow z dluga dostawa w dniach roboczych (chinczycy)

# IO patch - wymusza ladowanie lazy-loaded elementow w off-screen dialogu bocznym Allegro.
# Allegro uzywa IntersectionObserver do lazy-loadingu ofert w dialogu "Inne oferty produktu".
# Dialog jest renderowany poza viewport (x > viewport_width), wiec IO nigdy nie triggeruje.
# Patch zmienia callback IO tak zeby zawsze raportowac isIntersecting=true.
IO_PATCH_JS = r'''(function() {
    if (window.__ioPatchApplied) return;
    window.__ioPatchApplied = true;
    var OrigIO = IntersectionObserver;
    window.IntersectionObserver = function(callback, options) {
        var modifiedCallback = function(entries, observer) {
            var fakeEntries = entries.map(function(entry) {
                return {
                    boundingClientRect: entry.boundingClientRect,
                    intersectionRatio: 1.0,
                    intersectionRect: entry.boundingClientRect,
                    isIntersecting: true,
                    rootBounds: entry.rootBounds,
                    target: entry.target,
                    time: entry.time
                };
            });
            callback(fakeEntries, observer);
        };
        var obs = new OrigIO(modifiedCallback, options);
        return obs;
    };
    window.IntersectionObserver.prototype = OrigIO.prototype;
})();'''

# Polskie miesiace do parsowania daty dostawy
POLISH_MONTHS = {
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9, "paz": 10, "lis": 11, "gru": 12
}


def _easter_date(year: int) -> date:
    """Oblicza date Wielkanocy algorytmem Meeusa/Jonesa/Butchera."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _polish_holidays(year: int) -> set:
    """Zwraca zbior polskich swiat ustawowo wolnych od pracy."""
    easter = _easter_date(year)
    return {
        date(year, 1, 1),                   # Nowy Rok
        date(year, 1, 6),                   # Trzech Kroli
        easter,                              # Wielkanoc
        easter + timedelta(days=1),          # Poniedzialek Wielkanocny
        date(year, 5, 1),                   # Swieto Pracy
        date(year, 5, 3),                   # Konstytucja 3 Maja
        easter + timedelta(days=60),         # Boze Cialo
        date(year, 8, 15),                  # Wniebowziecie NMP
        date(year, 11, 1),                  # Wszystkich Swietych
        date(year, 11, 11),                 # Niepodleglosci
        date(year, 12, 25),                 # Boze Narodzenie
        date(year, 12, 26),                 # Drugi dzien swiat
    }


def _business_days_between(start: date, end: date) -> int:
    """Liczy dni robocze miedzy datami (bez weekendow i swiat polskich)."""
    if end <= start:
        return 0
    holidays = _polish_holidays(start.year)
    if end.year != start.year:
        holidays |= _polish_holidays(end.year)
    count = 0
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            count += 1
        current += timedelta(days=1)
    return count

# Cache dla wykluczonych sprzedawcow (unikamy zapytan do DB przy kazdym sprawdzeniu)
_excluded_sellers_cache: set = set()
_excluded_sellers_loaded: bool = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_excluded_sellers() -> set:
    """Pobiera liste wykluczonych sprzedawcow z bazy danych."""
    global _excluded_sellers_cache, _excluded_sellers_loaded
    
    if _excluded_sellers_loaded:
        return _excluded_sellers_cache
    
    try:
        from magazyn.db import get_session
        from magazyn.models import ExcludedSeller
        
        with get_session() as session:
            excluded = session.query(ExcludedSeller.seller_name).all()
            _excluded_sellers_cache = {e.seller_name for e in excluded}
            _excluded_sellers_loaded = True
            if _excluded_sellers_cache:
                logger.info(f"Zaladowano {len(_excluded_sellers_cache)} wykluczonych sprzedawcow")
    except Exception as e:
        logger.warning(f"Nie udalo sie pobrac wykluczonych sprzedawcow: {e}")
        _excluded_sellers_cache = set()
        _excluded_sellers_loaded = True
    
    return _excluded_sellers_cache


def reload_excluded_sellers():
    """Wymusza ponowne zaladowanie listy wykluczonych sprzedawcow."""
    global _excluded_sellers_loaded
    _excluded_sellers_loaded = False
    return get_excluded_sellers()


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
    is_super_seller: bool = False
    has_smart: bool = False
    offer_id: Optional[str] = None


@dataclass
class PriceCheckResult:
    """Wynik sprawdzenia cen dla oferty."""
    offer_id: str
    success: bool
    my_price: Optional[float] = None
    competitors: List[CompetitorOffer] = None
    cheapest_competitor: Optional[CompetitorOffer] = None
    my_position: int = 0
    competitors_all_count: int = 0  # Przed filtrami (kontekst)
    our_other_offers: List[CompetitorOffer] = None  # Nasze inne oferty z dialogu
    error: Optional[str] = None
    checked_at: str = ""
    
    def __post_init__(self):
        if self.competitors is None:
            self.competitors = []
        if self.our_other_offers is None:
            self.our_other_offers = []
        if not self.checked_at:
            self.checked_at = datetime.now().isoformat()


def parse_price(price_str: str) -> float:
    """Parsuje cene z formatu '206,00' do float."""
    return float(price_str.replace(",", ".").replace(" ", ""))


def parse_delivery_days(text: str) -> Optional[int]:
    """Parsuje tekst dostawy na liczbe dni ROBOCZYCH.
    
    Uwzglednia weekendy i polskie swieta ustawowe (Wielkanoc, Boze Cialo itd.).
    Dzieki temu w okresie swiatecznym normalni sprzedawcy nie sa odfiltrowywani.
    
    Rozpoznaje formaty:
    - 'dostawa pt. 6 lut.' -> dni robocze do 6 lutego
    - 'dostawa w sobote' -> oblicza dni robocze do soboty
    - 'dostawa za 2-3 dni' -> dni robocze do daty docelowej
    - '5 lut' -> dni robocze do 5 lutego
    - 'pojutrze' -> dni robocze
    - 'jutro' -> dni robocze
    - 'dzisiaj' -> 0
    """
    if not text:
        return None
    t = text.lower().strip()
    today = date.today()
    
    # 'dostawa od X' - pomijamy (nieznana data, czesto chinczycy)
    if re.match(r"^dostawa\s+od\s+\d", t):
        return 99  # Wysoka wartosc = odfiltruj
    
    # 'dostawa za X-Y dni'
    m = re.search(r"dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni", t)
    if m:
        avg_days = (int(m.group(1)) + int(m.group(2))) // 2
        target = today + timedelta(days=avg_days)
        return _business_days_between(today, target)
    
    # 'dostawa za X dni'
    m = re.search(r"dostawa\s+za\s+(\d+)\s*dni", t)
    if m:
        target = today + timedelta(days=int(m.group(1)))
        return _business_days_between(today, target)
    
    # 'X sty' lub 'pt. X sty' - konkretna data (np. '5 lut', 'pt. 6 lut.')
    # Usun opcjonalny dzien tygodnia na poczatku
    t_clean = re.sub(r'^dostawa\s+(?:pon|wt|[sś]r|czw|pt|sob|niedz)\.?\s*', 'dostawa ', t)
    m = re.search(r"(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|pa[zź]|lis|gru)", t_clean)
    if m:
        day = int(m.group(1))
        month_str = m.group(2).replace('ź', 'z')  # paz/paź -> paz
        month = POLISH_MONTHS.get(month_str, 1)
        try:
            target = date(today.year, month, day)
            if target < today:
                target = date(today.year + 1, month, day)
            return _business_days_between(today, target)
        except ValueError:
            pass
    
    # Dni tygodnia - z polskimi znakami i bez
    days_of_week = {
        "poniedzialek": 0, "poniedziałek": 0, "poniedział": 0, "pon": 0,
        "wtorek": 1, "wtor": 1, "wt": 1,
        "sroda": 2, "środa": 2, "srod": 2, "środ": 2, "sr": 2, "śr": 2,
        "czwartek": 3, "czwart": 3, "czw": 3,
        "piatek": 4, "piątek": 4, "piąt": 4, "piat": 4, "pt": 4,
        "sobota": 5, "sobot": 5, "sobo": 5, "sob": 5,
        "niedziela": 6, "niedziel": 6, "niedz": 6
    }
    for day_name, day_num in days_of_week.items():
        if day_name in t:
            today_weekday = today.weekday()
            days_ahead = day_num - today_weekday
            if days_ahead <= 0:
                days_ahead += 7
            target = today + timedelta(days=days_ahead)
            return _business_days_between(today, target)
    
    if "pojutrze" in t:
        target = today + timedelta(days=2)
        return _business_days_between(today, target)
    if "jutro" in t:
        target = today + timedelta(days=1)
        return _business_days_between(today, target)
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


async def extract_page_price(ws) -> Optional[float]:
    """Wyciaga cene oferty ze strony (widoczna dla kupujacego, z uwzglednieniem promocji)."""
    js_code = '''
    (function() {
        // Szukaj ceny w roznych miejscach na stronie oferty
        // 1. Aria label "cena z" na elemencie z cena
        const ariaPrice = document.querySelector('[aria-label*="cena z"]');
        if (ariaPrice) {
            const match = ariaPrice.getAttribute('aria-label').match(/(\\d+[,.]\\d{2})/);
            if (match) return match[1].replace(',', '.');
        }
        
        // 2. Meta tag og:price:amount
        const metaPrice = document.querySelector('meta[property="product:price:amount"]');
        if (metaPrice) return metaPrice.content;
        
        // 3. Szukaj elementu [data-testid] z cena
        const priceEl = document.querySelector('[data-testid="price"]');
        if (priceEl) {
            const match = priceEl.innerText.match(/(\\d+[,.]\\d{2})/);
            if (match) return match[1].replace(',', '.');
        }
        
        return null;
    })()
    '''
    result = await cdp_call(ws, "Runtime.evaluate",
                            {"expression": js_code, "returnByValue": True},
                            msg_id=50)
    value = result.get("result", {}).get("result", {}).get("value")
    if value:
        try:
            return float(str(value).replace(",", ".").replace(" ", ""))
        except (ValueError, TypeError):
            pass
    return None


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
        let container = document.querySelector('[data-box-name="ProductOffersListingContainer"]');
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
            // Link do oferty - szukaj offerId i pelny URL
            let offerId = null;
            let offerUrl = null;
            
            // 1. Szukaj linku /produkt/?offerId= (nowy format Allegro)
            const produktLink = art.querySelector('a[href*="/produkt/"]');
            if (produktLink) {
                const match = produktLink.href.match(/offerId=(\d+)/);
                if (match) offerId = match[1];
            }
            
            // 2. Szukaj linku /oferta/ (bezposredni link do oferty)
            if (!offerId) {
                const ofertaLink = art.querySelector('a[href*="/oferta/"]');
                if (ofertaLink) {
                    // URL w formacie /oferta/tytul-OFFER_ID
                    const match = ofertaLink.href.match(/\/oferta\/[^?#]*?-(\d{8,})/);
                    if (match) {
                        offerId = match[1];
                        offerUrl = ofertaLink.href;
                    }
                }
            }
            
            // 3. Szukaj dowolnego linku z offerId w parametrze
            if (!offerId) {
                const allLinks = art.querySelectorAll('a[href]');
                for (const link of allLinks) {
                    const match = link.href.match(/offerId=(\d+)/);
                    if (match) {
                        offerId = match[1];
                        break;
                    }
                }
            }
            
            // 4. Fallback: link /events/clicks z redirect do oferty
            if (!offerId) {
                const eventLink = art.querySelector('a[href*="/events/clicks"]');
                if (eventLink) {
                    const redirectMatch = eventLink.href.match(/redirect=([^&]+)/);
                    if (redirectMatch) {
                        const decoded = decodeURIComponent(redirectMatch[1]);
                        // Szukaj offerId= w zdekodowanym URL
                        const paramMatch = decoded.match(/offerId=(\d+)/);
                        if (paramMatch) {
                            offerId = paramMatch[1];
                        } else {
                            // Ostatni fallback: ID z URL /oferta/slug-ID
                            const slugMatch = decoded.match(/\/oferta\/[^?#]*?-(\d{8,})/);
                            if (slugMatch) offerId = slugMatch[1];
                        }
                        offerUrl = decoded;
                    }
                }
            }
            
            // Cena z aria-label - niezawodne zrodlo
            // <p aria-label="219,45 zł aktualna cena"> = cena aktualna
            // <button aria-label="-5% 229,00 zł cena z 30 dni ..."> = cena przed rabatem
            let ariaPrice = null;
            const priceEl = art.querySelector('p[aria-label*="aktualna cena"]');
            if (priceEl) {
                const m = priceEl.getAttribute('aria-label').match(/([\d\s]+(?:,\d{2})?)\s*zł/);
                if (m) ariaPrice = m[1].replace(/\s/g, '');
            }

            return {
                index: idx,
                offerId: offerId,
                offerUrl: offerUrl,
                ariaPrice: ariaPrice,
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
        js_offer_url = art.get("offerUrl")
        
        # Pomin artykuly bez ceny lub zbyt krotkie (reklamy, UI elementy)
        if not text or len(text) < 15 or "zł" not in text:
            logger.debug(f"Pominiety article {art.get('index')}: brak ceny lub za krotki")
            continue
        
        # Pomin recenzje produktu (moga pojawic sie w dialogu ofert)
        review_keywords = ("NAJBARDZIEJ POMOCNA", "Treść recenzji", "Tresc recenzji")
        if any(kw in text for kw in review_keywords):
            logger.debug(f"Pominiety article {art.get('index')}: recenzja produktu")
            continue
        
        # DEBUG: loguj surowy tekst kafelka
        logger.debug(f"=== ARTICLE {art.get('index')} ===")
        logger.debug(f"Raw text: {repr(text[:300])}")
        logger.debug(f"offerId: {offer_id}, offerUrl: {js_offer_url}")
        
        # Sprzedawca - dwa wzorce:
        # 1. "| \n sprzedawca" - normalne oferty konkurencji
        # 2. "od \n Super Sprzedawcy? \n | \n sprzedawca" LUB "od \n sprzedawca" - bez "|"
        seller_match = re.search(r'\|\s*\n\s*(\S+)', text)
        if not seller_match:
            # Fallback: szukaj po "od" (dla ofert bez "|", np. moja oferta)
            seller_match = re.search(r'\bod\s*\n(?:Super Sprzedawcy\s*\n)?\s*(\S+)', text)
        
        # Cena glowna - priorytetowo z aria-label (niezawodne),
        # fallback na parsowanie tekstu
        aria_price = art.get("ariaPrice")
        
        delivery_match = re.search(r'(\d+(?:,\d{2})?)\s*zł\s*z\s*dostaw', text)
        delivery_price_str = delivery_match.group(1) if delivery_match else None
        
        if aria_price:
            price_match_value = aria_price
            logger.debug(f"Cena z aria-label: {aria_price}")
        else:
            # Fallback: regex na tekst (usun kupony zeby nie falszowaly ceny)
            clean_text = re.sub(r'(?:Kupon|Cashback|Rabat)\s+\d+(?:,\d{2})?\s*zł', '', text)
            all_prices = re.findall(r'(\d+(?:,\d{2})?)\s*zł\s*\n', clean_text)
            price_match_value = all_prices[-1] if all_prices else None
            if price_match_value:
                logger.debug(f"Cena z tekstu (fallback): {price_match_value}")
        # Tekst dostawy - rozszerzone wzorce:
        # Formaty z Allegro:
        # - "dostawa pt. 6 lut." (dzien + data)
        # - "dostawa czw. 5 lut. – pt. 6 lut." (zakres)
        # - "dostawa pojutrze"
        # - "dostawa jutro"
        # - "dostawa w sobote"
        # - "dostawa za 2-3 dni"
        # - "dostawa od 5 dni"
        delivery_text_match = re.search(
            r'(dostawa\s+(?:'
            r'(?:pon|wt|[sś]r|czw|pt|sob|niedz)\.?\s+\d{1,2}\s+(?:sty|lut|mar|kwi|maj|cze|lip|sie|wrz|pa[zź]|lis|gru)\.?'  # "pt. 6 lut."
            r'|w\s+\w+'  # "w sobote"
            r'|za\s+\d+.*?dni'  # "za 2-3 dni"
            r'|od\s+\d+'  # "od 5"
            r'|\d{1,2}\s+(?:sty|lut|mar|kwi|maj|cze|lip|sie|wrz|pa[zź]|lis|gru)\.?'  # "6 lut"
            r'|pojutrze|jutro|dzisiaj|dzi[sś]'  # slowa
            r'))',
            text,
            re.IGNORECASE
        )
        # Czy to moja oferta? - sprawdz TYLKO nazwe sprzedawcy (nie "Top oferta" bo moze byc u konkurencji)
        seller = seller_match.group(1) if seller_match else "nieznany"
        is_mine = seller.lower() == MY_SELLER.lower()
        
        # Super Sprzedawca - tekst moze zawierac "Super Sprzedawc" (odmienne formy)
        is_super_seller = bool(re.search(r'Super\s+Sprzedawc', text))
        
        # Smart! - darmowa dostawa Smart
        has_smart = bool(re.search(r'Smart!|smart!', text))
        
        if price_match_value:
            price = parse_price(price_match_value)
            
            # Sanity check - cena < 1 zl to prawie na pewno blad parsowania
            if price < 1.0:
                logger.warning(f"Pominiety article {art.get('index')}: cena {price} zl < 1 zl (prawdopodobny blad parsowania)")
                continue
            
            total = parse_price(delivery_price_str) if delivery_price_str else price
            delivery_text = delivery_text_match.group(1) if delivery_text_match else ""
            delivery_days = parse_delivery_days(delivery_text)
            
            # DEBUG: loguj wykryte wartosci
            logger.debug(f"Seller: {seller}, Price: {price}, Delivery text: '{delivery_text}', Days: {delivery_days}")
            
            # Buduj URL oferty - preferuje bezposredni URL z JS
            offer_url = ""
            if js_offer_url:
                offer_url = js_offer_url
            elif offer_id:
                offer_url = f"https://allegro.pl/oferta/x-{offer_id}"
            elif seller and seller != "nieznany" and product_title:
                search_query = urllib.parse.quote(product_title[:50])
                offer_url = f"https://allegro.pl/listing?string={search_query}&sellerLogin={seller}"
            
            offers.append(CompetitorOffer(
                seller=seller,
                price=price,
                price_with_delivery=total,
                is_mine=is_mine,
                delivery_days=delivery_days,
                delivery_text=delivery_text,
                offer_url=offer_url,
                is_super_seller=is_super_seller,
                has_smart=has_smart,
                offer_id=offer_id,
            ))
    
    # Deduplikacja - ten sam offer_id lub (seller + price) to ta sama oferta
    seen = set()
    unique_offers = []
    for o in offers:
        if o.offer_id:
            key = o.offer_id
        else:
            key = f"{o.seller}_{o.price:.2f}"
        if key not in seen:
            seen.add(key)
            unique_offers.append(o)
        else:
            logger.debug(f"Duplikat oferty: {key} (seller={o.seller}, price={o.price})")
    
    if len(unique_offers) < len(offers):
        logger.info(f"Usunieto {len(offers) - len(unique_offers)} duplikatow ofert")
    
    return unique_offers


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
    
    if websockets is None:
        result.error = "Brak pakietu websockets - zainstaluj: pip install websockets"
        return result
    
    url = build_offer_url(offer_id, title)
    
    try:
        ws_url = await get_cdp_websocket_url(cdp_host, cdp_port)
        logger.debug(f"CDP WebSocket: {ws_url}")
        
        async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
            # Wstrzyknij IO patch - wymusza ladowanie lazy-loaded elementow
            # w off-screen dialogu bocznym Allegro
            await cdp_call(ws, "Page.enable", msg_id=900)
            add_script = await cdp_call(
                ws, "Page.addScriptToEvaluateOnNewDocument",
                {"source": IO_PATCH_JS}, msg_id=901
            )
            io_patch_id = add_script.get("result", {}).get("identifier")
            
            # Reset stanu - nawiguj do about:blank i zdrenuj bufor websocket
            # (konsumuje Page.loadEventFired z about:blank, zeby navigate_to_url
            # nie pomylil go z loadEventFired strony oferty)
            await cdp_call(ws, "Page.navigate", {"url": "about:blank"}, msg_id=902)
            await asyncio.sleep(0.3)
            # Zdrenuj bufor - usun wszystkie oczekujace eventy
            while True:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.2)
                except asyncio.TimeoutError:
                    break
            
            # Nawiguj do oferty
            await navigate_to_url(ws, url)
            
            # Czekaj na dialog
            if not await wait_for_dialog(ws):
                if io_patch_id:
                    try:
                        await cdp_call(ws, "Page.removeScriptToEvaluateOnNewDocument",
                                      {"identifier": io_patch_id}, msg_id=903)
                    except Exception:
                        pass
                result.error = "Dialog 'Inne oferty produktu' nie pojawil sie"
                return result
            
            # Przenies dialog "Inne oferty produktu" na ekran
            # UWAGA: strona ma wiele [role='dialog'] - musimy znalezc wlasciwy
            reposition_js = r'''(function() {
                var dialogs = document.querySelectorAll("[role='dialog']");
                for (var d of dialogs) {
                    if (d.innerText && d.innerText.includes('Inne oferty produktu')) {
                        d.style.cssText = 'position: fixed !important; left: 0 !important; top: 0 !important; width: 768px !important; min-height: 100vh !important; z-index: 999999 !important; overflow: auto !important;';
                        d.scrollTop = 0;
                        return true;
                    }
                }
                return false;
            })()''''
            await cdp_call(ws, "Runtime.evaluate",
                          {"expression": reposition_js, "returnByValue": True},
                          msg_id=910)
            
            # Pauza na zaladowanie lazy-loaded ofert (IO + reposition trigger)
            await asyncio.sleep(7)
            
            # Diagnostyka: sprawdz stan lazy elementow we WLASCIWYM dialogu
            diag_js = r'''(function() {
                var dialogs = document.querySelectorAll("[role='dialog']");
                var target = null;
                for (var d of dialogs) {
                    if (d.innerText && d.innerText.includes('Inne oferty produktu')) {
                        target = d;
                        break;
                    }
                }
                if (!target) return {dialog: false, totalDialogs: dialogs.length};
                var lazy = target.querySelectorAll('.lazyload').length;
                var loaded = target.querySelectorAll('.lazyloaded').length;
                var articles = target.querySelectorAll('article').length;
                var container = target.querySelector('[data-box-name="ProductOffersListingContainer"]');
                var htmlLen = target.innerHTML.length;
                return {
                    dialog: true,
                    ioPatch: !!window.__ioPatchApplied,
                    lazy: lazy,
                    loaded: loaded,
                    articles: articles,
                    container: !!container,
                    htmlLen: htmlLen,
                    totalDialogs: dialogs.length
                };
            })()''''
            diag = await cdp_call(ws, "Runtime.evaluate",
                                  {"expression": diag_js, "returnByValue": True},
                                  msg_id=950)
            diag_val = diag.get("result", {}).get("result", {}).get("value", {})
            logger.info(f"Diagnostyka oferty {offer_id}: {diag_val}")
            
            # Wyciagnij oferty
            all_offers = await extract_competitor_offers(ws, title)
            
            # Usun IO patch (nie zaklocaj normalnego przegladania)
            if io_patch_id:
                try:
                    await cdp_call(ws, "Page.removeScriptToEvaluateOnNewDocument",
                                  {"identifier": io_patch_id}, msg_id=904)
                except Exception:
                    pass
            
            if not all_offers:
                result.error = "Brak ofert w dialogu"
                return result
            
            # Sprawdzana oferta NIE pojawia sie w dialogu (to jest jej strona)
            # Ale inne nasze oferty tego samego produktu MOGA sie pojawic
            our_other_offers = [o for o in all_offers if o.is_mine]
            result.our_other_offers = our_other_offers
            if our_other_offers:
                logger.info(f"Znaleziono {len(our_other_offers)} naszych innych ofert w dialogu: "
                            f"{', '.join(o.offer_id or '?' for o in our_other_offers)}")
            
            # my_price: ustawiana z zewnatrz (badge API -> API bazowa)
            # Dialog nie zawiera sprawdzanej oferty
            
            # Pobierz wykluczonych sprzedawcow
            excluded_sellers = get_excluded_sellers()
            
            # Konkurencja = wszystkie oferty POZA naszymi (inne nasze to "inna OK")
            competitors_all = [o for o in all_offers if not o.is_mine]
            result.competitors_all_count = len(competitors_all)
            competitors_filtered = [
                o for o in competitors_all
                if (o.delivery_days is None or o.delivery_days < max_delivery_days)
                and o.seller not in excluded_sellers
            ]
            
            # Loguj odfiltrowanych
            filtered_by_delivery = len([o for o in competitors_all if o.delivery_days is not None and o.delivery_days >= max_delivery_days])
            filtered_by_excluded = len([o for o in competitors_all if o.seller in excluded_sellers])
            
            if filtered_by_delivery > 0:
                logger.info(f"Odfiltrowano {filtered_by_delivery} ofert z dostawa >= {max_delivery_days} dni roboczych")
            if filtered_by_excluded > 0:
                logger.info(f"Odfiltrowano {filtered_by_excluded} ofert od wykluczonych sprzedawcow")
            
            result.competitors = competitors_filtered
            
            # Najtanszy konkurent (tylko z szybka dostawa i bez wykluczonych)
            # Sortuj po cenie bazowej (price), nie z dostawa - wszyscy uzywaja Smart
            if competitors_filtered:
                result.cheapest_competitor = min(competitors_filtered, key=lambda x: x.price)
            
            # Pozycja: wstawiamy nasza cene (z API) do rankingu konkurentow
            # Inne nasze oferty NIE uczestnicza w rankingu (to "inna OK")
            if result.my_price and competitors_filtered:
                result.my_position = 1 + sum(
                    1 for c in competitors_filtered if c.price < result.my_price
                )
            elif result.my_price:
                result.my_position = 1
            
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
        print(f"\nNajtansza konkurencja: {c.seller} - {c.price:.2f} zl{days_info}")
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
