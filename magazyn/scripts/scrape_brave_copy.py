#!/usr/bin/env python3
"""
Scraper Allegro z kopia profilu Brave.

Kopiuje profil Brave do katalogu tymczasowego i uzywa go z Playwright.
Dzieki temu mozna uzywac zalogowanej sesji bez zamykania przegladarki.

Wymagania:
    pip install playwright
    playwright install chromium

Uzycie:
    python scrape_brave_copy.py <allegro_url>
    python scrape_brave_copy.py --test
"""

import asyncio
import json
import re
import shutil
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

# Sciezka do profilu Brave
BRAVE_USER_DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data"

# Stale
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 4

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


def copy_brave_profile(dest_dir: Path) -> bool:
    """Kopiuje istotne pliki profilu Brave."""
    if not BRAVE_USER_DATA.exists():
        return False
    
    default_profile = BRAVE_USER_DATA / "Default"
    if not default_profile.exists():
        return False
    
    dest_default = dest_dir / "Default"
    dest_default.mkdir(parents=True, exist_ok=True)
    
    # Pliki do skopiowania (minimalna ilosc dla cookies)
    files_to_copy = [
        "Cookies",
        "Cookies-journal",
        "Network/Cookies",
        "Network/Cookies-journal",
        "Local State",
        "Preferences",
        "Secure Preferences",
    ]
    
    # Kopiuj Local State z glownego katalogu
    local_state = BRAVE_USER_DATA / "Local State"
    if local_state.exists():
        shutil.copy2(local_state, dest_dir / "Local State")
    
    # Kopiuj pliki profilu
    for file_path in files_to_copy:
        src = default_profile / file_path
        if src.exists():
            dst = dest_default / file_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
                print(f"  Skopiowano: {file_path}")
            except Exception as e:
                print(f"  Nie mozna skopiowac {file_path}: {e}")
    
    return True


async def scrape_allegro_with_brave_copy(
    url: str,
    max_delivery_days: int = MAX_DELIVERY_DAYS,
    headless: bool = True,
) -> ScrapingResult:
    """Scrapuje Allegro uzywajac kopii profilu Brave."""
    
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return ScrapingResult(success=False, error="Zainstaluj: pip install playwright")
    
    result = ScrapingResult(success=False)
    temp_dir = None
    
    try:
        # Stworz tymczasowy katalog dla profilu
        temp_dir = Path(tempfile.mkdtemp(prefix="brave_profile_"))
        print(f"Tworzenie kopii profilu Brave w: {temp_dir}")
        
        if not copy_brave_profile(temp_dir):
            return ScrapingResult(success=False, error="Nie mozna skopiowac profilu Brave")
        
        async with async_playwright() as p:
            # Uruchom z kopia profilu
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(temp_dir),
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                viewport={"width": 1920, "height": 1080},
                locale="pl-PL",
                ignore_https_errors=True,
            )
            
            page = await context.new_page()
            
            # Dodaj anti-detection
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                window.chrome = {runtime: {}};
            """)
            
            try:
                # Krok 1: Otworz strone oferty
                print(f"[1/3] Otwieram strone oferty...")
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Sprawdz czy strona zaladowana
                html = await page.content()
                title = await page.title()
                
                print(f"      Tytul: {title}")
                print(f"      HTML size: {len(html)} bytes")
                
                if len(html) < 10000 or title.lower() == "allegro.pl":
                    # Screenshot do debugowania
                    screenshot_path = Path("debug_screenshot.png")
                    await page.screenshot(path=str(screenshot_path))
                    print(f"      Screenshot: {screenshot_path}")
                    
                    if "captcha-delivery.com" in html or "datadome" in html.lower():
                        result.error = "DataDome captcha - sesja nie zaladowana poprawnie"
                    else:
                        result.error = f"Strona nie zaladowala sie poprawnie (tytul: {title})"
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
                await context.close()
    
    finally:
        # Usun tymczasowy katalog
        if temp_dir and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
    
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


async def test_scraper():
    test_url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323"
    
    print("=" * 60)
    print("BRAVE PROFILE COPY SCRAPER TEST")
    print("=" * 60)
    print(f"URL: {test_url}")
    print()
    
    # Headful dla testu
    result = await scrape_allegro_with_brave_copy(test_url, headless=False)
    print()
    print(format_result(result))
    
    return result.success


async def main():
    if len(sys.argv) < 2:
        print("Uzycie:")
        print("  python scrape_brave_copy.py <allegro_url>")
        print("  python scrape_brave_copy.py --test")
        return
    
    if sys.argv[1] == "--test":
        success = await test_scraper()
        sys.exit(0 if success else 1)
    
    url = sys.argv[1]
    headless = "--headless" in sys.argv
    
    result = await scrape_allegro_with_brave_copy(url, headless=headless)
    
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
