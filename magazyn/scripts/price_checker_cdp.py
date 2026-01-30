#!/usr/bin/env python3
"""
Price Checker - scraper cen konkurencji przez CDP.

Laczy sie z uruchomiona przegladarka Brave/Chrome przez Chrome DevTools Protocol.
Pobiera linki ofert z bazy danych retrievershop-suite i sprawdza ceny konkurencji.

LOKALNE UZYCIE:
1. Uruchom osobna instancje Brave (nie Twoja glowna!):
   "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" ^
       --user-data-dir="C:\Users\sucho\AppData\Local\BraveSoftware\Brave-Browser-Scraper" ^
       --remote-debugging-port=9223

2. Zaloguj sie na Allegro w tej przegladarce

3. Uruchom:
   python price_checker_cdp.py --check-offers
   python price_checker_cdp.py --offer-id 18180401323

NA MINIPC Z VNC:
1. Zainstaluj Xvfb i x11vnc:
   sudo apt install xvfb x11vnc chromium-browser

2. Uruchom wirtualny display:
   Xvfb :99 -screen 0 1920x1080x24 &
   export DISPLAY=:99
   x11vnc -display :99 -forever -nopw &

3. Uruchom Chrome z debugowaniem:
   chromium-browser --remote-debugging-port=9222 --no-first-run &

4. Polacz sie przez VNC (port 5900) i zaloguj na Allegro

5. Uruchom scraper:
   python price_checker_cdp.py --cdp-url http://localhost:9222 --check-offers

Wymagania:
    pip install playwright sqlalchemy
"""

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

# Dodaj katalog magazyn do sciezki
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Zainstaluj playwright: pip install playwright")
    sys.exit(1)


# Stale
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 4
DEFAULT_CDP_URL = "http://localhost:9223"

POLISH_MONTHS = {
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9, "paz": 10, "lis": 11, "gru": 12
}


@dataclass
class CompetitorOffer:
    """Dane oferty konkurencji."""
    seller: str
    price: float
    currency: str = "PLN"
    delivery_text: str = ""
    delivery_days: Optional[int] = None
    is_super_seller: bool = False
    offer_url: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PriceCheckResult:
    """Wynik sprawdzenia ceny."""
    success: bool
    offer_id: str
    my_price: Optional[float] = None
    error: Optional[str] = None
    competitors: List[CompetitorOffer] = None
    cheapest: Optional[CompetitorOffer] = None
    price_diff: Optional[float] = None
    checked_at: str = ""
    
    def __post_init__(self):
        if self.competitors is None:
            self.competitors = []
        if not self.checked_at:
            self.checked_at = datetime.now().isoformat()


def parse_delivery_days(text: str) -> Optional[int]:
    """Parsuje tekst dostawy na liczbe dni."""
    if not text:
        return None
    t = text.lower().strip()
    
    # "dostawa od X" - pomijamy (nieznana data)
    if re.match(r"^dostawa\s+od\s+\d", t):
        return None
    
    # "dostawa za X-Y dni"
    m = re.search(r"dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni", t)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    
    # "X sty" - konkretna data
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
    
    if "jutro" in t:
        return 1
    if "dzisiaj" in t or "dzis" in t:
        return 0
    
    return None


def build_offer_url(offer_id: str, title: str = "") -> str:
    """Buduje URL oferty Allegro."""
    # Jesli offer_id to pelny URL, zwroc go
    if offer_id.startswith("http"):
        return offer_id
    
    # Jesli mamy tytul, zbuduj slug
    if title:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
        return f"https://allegro.pl/oferta/{slug}-{offer_id}"
    
    # Tylko ID - Allegro przekieruje
    return f"https://allegro.pl/oferta/{offer_id}"


async def check_offer_price(
    page,
    offer_id: str,
    title: str = "",
    my_price: Optional[float] = None,
    max_delivery_days: int = MAX_DELIVERY_DAYS,
) -> PriceCheckResult:
    """
    Sprawdza ceny konkurencji dla danej oferty.
    
    Args:
        page: Playwright page object
        offer_id: ID oferty Allegro
        title: Tytul oferty (opcjonalny, do budowania URL)
        my_price: Nasza cena (opcjonalna, do porownania)
        max_delivery_days: Maksymalna liczba dni dostawy do filtrowania
    """
    result = PriceCheckResult(
        success=False,
        offer_id=offer_id,
        my_price=my_price,
    )
    
    url = build_offer_url(offer_id, title)
    
    try:
        # Krok 1: Otworz strone oferty
        print(f"  [1/3] Otwieram: {url[:80]}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        
        html = await page.content()
        page_title = await page.title()
        
        if len(html) < 5000 or "captcha" in html.lower():
            result.error = "DataDome captcha lub strona nie zaladowala sie"
            return result
        
        # Krok 2: Znajdz link do porownania ofert
        print(f"  [2/3] Szukam linku do porownania...")
        
        # Szukamy linku "inne oferty" lub "porownaj ceny"
        comparison_link = await page.query_selector('a[href*="/oferty-produktu/"]')
        
        if not comparison_link:
            # Moze nie ma innych ofert tego produktu
            result.error = "Brak linku do porownania - produkt moze nie miec konkurencji"
            result.success = True  # To nie blad, po prostu brak konkurencji
            return result
        
        comparison_url = await comparison_link.get_attribute("href")
        if not comparison_url.startswith("http"):
            comparison_url = "https://allegro.pl" + comparison_url
        
        # Krok 3: Pobierz strone porownania
        print(f"  [3/3] Pobieram strone porownania...")
        await page.goto(comparison_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)  # Daj czas na zaladowanie React
        
        html = await page.content()
        
        # Sprobuj rozne metody ekstrakcji danych
        competitors = await extract_competitors_from_page(page, html, max_delivery_days)
        
        if not competitors:
            result.error = "Nie udalo sie wydobyc danych konkurencji"
            return result
        
        # Filtruj i sortuj
        competitors.sort(key=lambda x: x.price)
        
        result.competitors = competitors
        result.success = True
        
        if competitors:
            result.cheapest = competitors[0]
            if my_price:
                result.price_diff = round(my_price - competitors[0].price, 2)
        
    except Exception as e:
        result.error = str(e)
    
    return result


async def extract_competitors_from_page(
    page,
    html: str,
    max_delivery_days: int,
) -> List[CompetitorOffer]:
    """Wydobywa dane konkurencji ze strony porownania."""
    
    # Metoda 1: JSON w __listing_StoreState
    match = re.search(r"__listing_StoreState\s*=\s*({.+?});\s*</script>", html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return parse_listing_store_state(data, max_delivery_days)
        except:
            pass
    
    # Metoda 2: Ekstrakcja z DOM
    return await extract_from_dom(page, max_delivery_days)


def parse_listing_store_state(data: dict, max_delivery_days: int) -> List[CompetitorOffer]:
    """Parsuje dane z __listing_StoreState."""
    offers = []
    elements = data.get("items", {}).get("elements", [])
    
    for el in elements:
        seller = el.get("seller", {})
        seller_login = seller.get("login", "Nieznany")
        
        # Pomin nasza oferte
        if seller_login.lower() == MY_SELLER.lower():
            continue
        
        price_info = el.get("price", {}).get("mainPrice", {}) or el.get("price", {})
        delivery = el.get("shipping", {}).get("delivery", {})
        delivery_label = delivery.get("label", {}).get("text", "")
        
        try:
            price = float(price_info.get("amount", 0))
        except:
            continue
        
        if price <= 0:
            continue
        
        delivery_days = parse_delivery_days(delivery_label)
        
        # Filtruj po czasie dostawy
        if delivery_days is not None and delivery_days > max_delivery_days:
            continue
        
        offer = CompetitorOffer(
            seller=seller_login,
            price=price,
            currency=price_info.get("currency", "PLN"),
            delivery_text=delivery_label,
            delivery_days=delivery_days,
            is_super_seller=seller.get("superSeller", False),
            offer_url=el.get("url", ""),
        )
        offers.append(offer)
    
    return offers


async def extract_from_dom(page, max_delivery_days: int) -> List[CompetitorOffer]:
    """Wydobywa dane konkurencji bezposrednio z DOM."""
    
    # Ta metoda wymaga dokladniejszego zbadania struktury strony
    # Na razie zwracamy pusta liste
    print("    UWAGA: Ekstrakcja z DOM niezaimplementowana - strona uzywa React bez SSR")
    return []


async def connect_to_browser(cdp_url: str):
    """Laczy sie z przegladarka przez CDP."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            return browser
        except Exception as e:
            print(f"BLAD: Nie mozna polaczyc z przegladarka: {e}")
            print(f"\nUpewnij sie, ze przegladarka jest uruchomiona z flaga --remote-debugging-port")
            return None


async def check_single_offer(cdp_url: str, offer_id: str, title: str = "", my_price: float = None):
    """Sprawdza pojedyncza oferte."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            print(f"BLAD: {e}")
            return None
        
        contexts = browser.contexts
        if not contexts:
            print("BLAD: Brak otwartego kontekstu przegladarki")
            return None
        
        page = await contexts[0].new_page()
        
        try:
            result = await check_offer_price(page, offer_id, title, my_price)
            return result
        finally:
            await page.close()


async def check_offers_from_db(cdp_url: str, limit: int = 10):
    """Sprawdza oferty z bazy danych."""
    
    # Import modeli
    try:
        from magazyn.models import AllegroOffer, AllegroPriceHistory
        from magazyn.db import get_session
    except ImportError as e:
        print(f"BLAD: Nie mozna zaimportowac modulow magazyn: {e}")
        print("Uruchom z katalogu retrievershop-suite lub ustaw PYTHONPATH")
        return
    
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            print(f"BLAD: {e}")
            return
        
        contexts = browser.contexts
        if not contexts:
            print("BLAD: Brak otwartego kontekstu przegladarki")
            return
        
        page = await contexts[0].new_page()
        
        try:
            # Pobierz oferty z bazy
            with get_session() as session:
                offers = session.query(AllegroOffer).filter(
                    AllegroOffer.publication_status == "ACTIVE"
                ).limit(limit).all()
                
                print(f"Znaleziono {len(offers)} aktywnych ofert")
                
                for i, offer in enumerate(offers, 1):
                    print(f"\n[{i}/{len(offers)}] {offer.title[:50]}...")
                    print(f"  ID: {offer.offer_id}, Cena: {offer.price} PLN")
                    
                    result = await check_offer_price(
                        page,
                        offer.offer_id,
                        offer.title,
                        float(offer.price),
                    )
                    
                    if result.success:
                        if result.competitors:
                            print(f"  Konkurencja: {len(result.competitors)} ofert")
                            if result.cheapest:
                                print(f"  Najtanszy: {result.cheapest.seller} @ {result.cheapest.price} PLN")
                                if result.price_diff:
                                    sign = "+" if result.price_diff > 0 else ""
                                    print(f"  Roznica: {sign}{result.price_diff} PLN")
                            
                            # Zapisz do historii
                            history = AllegroPriceHistory(
                                offer_id=offer.offer_id,
                                product_size_id=offer.product_size_id,
                                price=offer.price,
                                recorded_at=datetime.now().isoformat(),
                                competitor_price=Decimal(str(result.cheapest.price)) if result.cheapest else None,
                                competitor_seller=result.cheapest.seller if result.cheapest else None,
                                competitor_url=result.cheapest.offer_url if result.cheapest else None,
                                competitor_delivery_days=result.cheapest.delivery_days if result.cheapest else None,
                            )
                            session.add(history)
                        else:
                            print(f"  Brak konkurencji")
                    else:
                        print(f"  BLAD: {result.error}")
                    
                    # Opoznienie miedzy zapytaniami
                    await asyncio.sleep(2)
                
                session.commit()
                print("\nZapisano wyniki do bazy")
        
        finally:
            await page.close()


def main():
    parser = argparse.ArgumentParser(description="Price Checker - sprawdza ceny konkurencji")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL, help="URL CDP przegladarki")
    parser.add_argument("--offer-id", help="ID pojedynczej oferty do sprawdzenia")
    parser.add_argument("--check-offers", action="store_true", help="Sprawdz oferty z bazy danych")
    parser.add_argument("--limit", type=int, default=10, help="Limit ofert do sprawdzenia")
    
    args = parser.parse_args()
    
    if args.offer_id:
        result = asyncio.run(check_single_offer(args.cdp_url, args.offer_id))
        if result:
            print(json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str))
    elif args.check_offers:
        asyncio.run(check_offers_from_db(args.cdp_url, args.limit))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
