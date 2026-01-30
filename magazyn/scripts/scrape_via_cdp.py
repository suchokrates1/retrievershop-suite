#!/usr/bin/env python3
"""
Scraper Allegro poprzez polaczenie z uruchomiona przegladarka Brave.

Uzycie:
1. Uruchom Brave z flaga debugowania:
   "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222

2. Otworz Allegro w przegladarce i zaloguj sie

3. Uruchom skrypt:
   python scrape_via_cdp.py <allegro_url>

Wymagania:
    pip install playwright
"""

import asyncio
import json
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict


# Stale
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 4
CDP_URL = "http://localhost:9222"

POLISH_MONTHS = {
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9, "paz": 10, "lis": 11, "gru": 12
}


@dataclass
class CompetitorOffer:
    seller: str
    price: float
    currency: str = "PLN"
    delivery_text: str = ""
    delivery_days: Optional[int] = None
    is_super_seller: bool = False
    offer_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScrapingResult:
    success: bool
    error: Optional[str] = None
    my_price: Optional[float] = None
    competitors: List[CompetitorOffer] = None
    cheapest: Optional[CompetitorOffer] = None
    price_diff: Optional[float] = None
    total_offers: int = 0
    
    def __post_init__(self):
        if self.competitors is None:
            self.competitors = []


def parse_delivery_days(text: str) -> Optional[int]:
    if not text:
        return None
    t = text.lower().strip()
    if re.match(r"^dostawa\s+od\s+\d", t):
        return None
    m = re.search(r"dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni", t)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
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


async def scrape_via_cdp(
    url: str,
    max_delivery_days: int = MAX_DELIVERY_DAYS,
    cdp_url: str = CDP_URL,
) -> ScrapingResult:
    """Scrapuje Allegro przez CDP - polaczenie z uruchomiona przegladarka."""
    
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return ScrapingResult(success=False, error="Zainstaluj: pip install playwright")
    
    result = ScrapingResult(success=False)
    
    async with async_playwright() as p:
        try:
            print(f"Laczenie z przegladarka: {cdp_url}")
            browser = await p.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            return ScrapingResult(
                success=False, 
                error=f"Nie mozna polaczyc z Brave. Uruchom przegladarke z flaga --remote-debugging-port=9222\nBlad: {e}"
            )
        
        # Pobierz istniejacy kontekst
        contexts = browser.contexts
        if not contexts:
            return ScrapingResult(success=False, error="Brak otwartego kontekstu przegladarki")
        
        context = contexts[0]
        page = await context.new_page()
        
        try:
            # Krok 1: Otworz strone oferty
            print(f"[1/3] Otwieram strone oferty...")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Sprawdz czy strona zaladowana
            html = await page.content()
            title = await page.title()
            
            print(f"      Tytul: {title}")
            print(f"      HTML size: {len(html)} bytes")
            
            if len(html) < 10000:
                if "captcha-delivery.com" in html or "datadome" in html.lower():
                    result.error = "DataDome captcha - sesja nie jest zalogowana"
                else:
                    result.error = "Strona nie zaladowala sie poprawnie"
                return result
            
            # Krok 2: Znajdz URL porownania
            print(f"[2/3] Szukam linku do porownania...")
            links = await page.query_selector_all('a[href*="/oferty-produktu/"]')
            
            comparison_url = None
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    comparison_url = ("https://allegro.pl" + href) if href.startswith("/") else href
                    break
            
            if not comparison_url:
                result.error = "Nie znaleziono linku do porownania ofert"
                return result
            
            print(f"      Znaleziono: {comparison_url}")
            
            # Krok 3: Pobierz strone porownania
            print(f"[3/3] Pobieram strone porownania...")
            await page.goto(comparison_url, wait_until="networkidle", timeout=60000)
            
            html = await page.content()
            
            if len(html) < 5000:
                result.error = "Strona porownania nie zaladowala sie"
                return result
            
            # Parsuj JSON z danymi
            match = re.search(r"__listing_StoreState\s*=\s*({.+?});\s*</script>", html, re.DOTALL)
            if not match:
                result.error = "Nie znaleziono danych ofert w HTML"
                return result
            
            data = json.loads(match.group(1))
            elements = data.get("items", {}).get("elements", [])
            
            print(f"      Znaleziono {len(elements)} ofert")
            
            # Przetwarzaj oferty
            offers = []
            for el in elements:
                seller = el.get("seller", {})
                price_info = el.get("price", {}).get("mainPrice", {}) or el.get("price", {})
                delivery = el.get("shipping", {}).get("delivery", {})
                delivery_label = delivery.get("label", {}).get("text", "")
                
                try:
                    price = float(price_info.get("amount", 0))
                except:
                    continue
                
                if price <= 0:
                    continue
                
                offer = CompetitorOffer(
                    seller=seller.get("login", "Nieznany"),
                    price=price,
                    currency=price_info.get("currency", "PLN"),
                    delivery_text=delivery_label,
                    delivery_days=parse_delivery_days(delivery_label),
                    is_super_seller=seller.get("superSeller", False),
                    offer_id=el.get("id", ""),
                )
                offers.append(offer)
            
            # Filtruj po czasie dostawy
            filtered = [o for o in offers if o.delivery_days is None or o.delivery_days <= max_delivery_days]
            
            # Znajdz moja oferte
            my_offer = next((o for o in filtered if o.seller.lower() == MY_SELLER.lower()), None)
            if my_offer:
                result.my_price = my_offer.price
            
            # Konkurenci
            competitors = [o for o in filtered if o.seller.lower() != MY_SELLER.lower()]
            competitors.sort(key=lambda x: x.price)
            
            result.competitors = competitors
            result.total_offers = len(filtered)
            
            if competitors:
                result.cheapest = competitors[0]
                if result.my_price:
                    result.price_diff = round(result.my_price - competitors[0].price, 2)
            
            result.success = True
            
        except Exception as e:
            result.error = str(e)
        
        finally:
            await page.close()
            # Nie zamykamy browsera - jest to przegladarka uzytkownika!
    
    return result


def format_result(result: ScrapingResult) -> str:
    lines = []
    
    if not result.success:
        return f"BLAD: {result.error}"
    
    lines.append(f"Moja cena: {result.my_price} PLN" if result.my_price else "Moja oferta nie znaleziona")
    lines.append(f"Konkurentow: {len(result.competitors)}")
    lines.append(f"Wszystkich ofert (po filtrze): {result.total_offers}")
    
    if result.cheapest:
        lines.append(f"\nNajtanszy: {result.cheapest.seller} @ {result.cheapest.price} PLN")
        if result.cheapest.delivery_text:
            lines.append(f"  Dostawa: {result.cheapest.delivery_text}")
        if result.price_diff is not None:
            sign = "+" if result.price_diff > 0 else ""
            lines.append(f"  Roznica: {sign}{result.price_diff} PLN")
    
    if result.competitors:
        lines.append("\n--- Wszyscy konkurenci ---")
        for c in result.competitors[:15]:
            days = f"{c.delivery_days}d" if c.delivery_days is not None else "?"
            super_mark = " [SS]" if c.is_super_seller else ""
            lines.append(f"  {c.seller:25} | {c.price:>8.2f} PLN | {days:>4}{super_mark}")
        if len(result.competitors) > 15:
            lines.append(f"  ... i {len(result.competitors) - 15} wiecej")
    
    return "\n".join(lines)


async def start_brave_debug_mode():
    """Instrukcje jak uruchomic Brave w trybie debugowania."""
    import subprocess
    import os
    
    brave_paths = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    
    brave_exe = None
    for path in brave_paths:
        if os.path.exists(path):
            brave_exe = path
            break
    
    if not brave_exe:
        print("Nie znaleziono Brave. Zainstaluj przegladarke lub podaj sciezke reczne.")
        return
    
    print("Uruchamiam Brave w trybie debugowania...")
    print(f"Sciezka: {brave_exe}")
    
    # Uruchom Brave z debugowaniem
    subprocess.Popen([
        brave_exe,
        "--remote-debugging-port=9222",
    ])
    
    print("\nBrave uruchomiony! Teraz:")
    print("1. Zaloguj sie na Allegro w przegladarce")
    print("2. Uruchom: python scrape_via_cdp.py <url>")


async def test_scraper():
    test_url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323"
    
    print("=" * 60)
    print("CDP SCRAPER TEST (polaczenie z uruchomiona przegladarka)")
    print("=" * 60)
    print(f"URL: {test_url}")
    print()
    
    result = await scrape_via_cdp(test_url)
    print()
    print(format_result(result))
    
    return result.success


async def main():
    if len(sys.argv) < 2:
        print("Uzycie:")
        print("  python scrape_via_cdp.py <allegro_url>")
        print("  python scrape_via_cdp.py --test")
        print("  python scrape_via_cdp.py --start-brave")
        print()
        print("KROK 1: Uruchom Brave w trybie debugowania:")
        print('  "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe" --remote-debugging-port=9222')
        print()
        print("KROK 2: Otworz Allegro i zaloguj sie")
        print()
        print("KROK 3: Uruchom skrypt")
        return
    
    if sys.argv[1] == "--start-brave":
        await start_brave_debug_mode()
        return
    
    if sys.argv[1] == "--test":
        success = await test_scraper()
        sys.exit(0 if success else 1)
    
    url = sys.argv[1]
    
    result = await scrape_via_cdp(url)
    
    if result.success:
        print(json.dumps({
            "success": True,
            "my_price": result.my_price,
            "total_offers": result.total_offers,
            "competitor_count": len(result.competitors),
            "cheapest": result.cheapest.to_dict() if result.cheapest else None,
            "price_diff": result.price_diff,
            "competitors": [c.to_dict() for c in result.competitors],
        }, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"success": False, "error": result.error}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
