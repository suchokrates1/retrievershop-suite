#!/usr/bin/env python3
"""
Allegro Price Scraper using Stealth-Requests
Nowa metoda scrapingu bez headless browser - czysty HTTP z imitacja Chrome.

Zalety:
- Brak Selenium/Playwright - szybsze, mniej zasobow
- curl_cffi imituje Chrome TLS fingerprint
- Automatyczna rotacja User-Agent
- Retry logic dla 429/503

Wady:
- Nie radzi sobie z JavaScript rendering (SPA)
- DataDome moze wykryc brak JS

Instalacja:
    pip install stealth_requests[parsers]

Uzycie:
    python stealth_requests_scraper.py <allegro_url>
    python stealth_requests_scraper.py --test
"""

import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from decimal import Decimal, InvalidOperation

try:
    import stealth_requests as requests
    from stealth_requests import StealthSession
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    requests = None
    StealthSession = None

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    BeautifulSoup = None


# Stale
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 4

# Oxylabs Web Unblocker - bypass DataDome
OXYLABS_USER = "suchokrates1_B9Mtv"
OXYLABS_PASS = "S+vhqka1b=oSW0"
OXYLABS_PROXY = {
    "http": f"http://{OXYLABS_USER}:{OXYLABS_PASS}@unblock.oxylabs.io:60000",
    "https": f"http://{OXYLABS_USER}:{OXYLABS_PASS}@unblock.oxylabs.io:60000",
}

POLISH_MONTHS = {
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9, "paz": 10, "lis": 11, "gru": 12
}


@dataclass
class CompetitorOffer:
    """Dane oferty konkurenta."""
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
    """Wynik scrapowania."""
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
    """Parsuje tekst dostawy na liczbe dni."""
    if not text:
        return None
    
    t = text.lower().strip()
    
    # Pomin "Dostawa od X zl" - to cena, nie czas
    if re.match(r"^dostawa\s+od\s+\d", t):
        return None
    
    # "dostawa za 2-3 dni"
    m = re.search(r"dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni", t)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    
    # "15 sty" - data
    m = re.search(r"(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paz|lis|gru)", t)
    if m:
        day, month = int(m.group(1)), POLISH_MONTHS.get(m.group(2), 1)
        today = datetime.now()
        try:
            target = datetime(today.year, month, day)
            if target < today:
                target = datetime(today.year + 1, month, day)
            return (target - today).days
        except Exception:
            pass
    
    if "jutro" in t:
        return 1
    if "dzisiaj" in t or "dzis" in t:
        return 0
    
    return None


def extract_offer_id(url: str) -> str:
    """Wyciaga ID oferty z URL Allegro."""
    match = re.search(r'-(\d{10,})(?:\?|#|$)', url)
    return match.group(1) if match else ""


def parse_price(price_str: str) -> Optional[float]:
    """Parsuje cene z formatu polskiego (123,45 zl)."""
    if not price_str:
        return None
    clean = re.sub(r'[^\d,.]', '', price_str)
    clean = clean.replace(',', '.')
    try:
        return float(clean)
    except ValueError:
        return None


def extract_comparison_url(html: str, base_url: str) -> Optional[str]:
    """Znajduje URL strony porownania ofert."""
    # Szukaj linku do /oferty-produktu/
    match = re.search(r'href="([^"]*\/oferty-produktu\/[^"]*)"', html)
    if match:
        href = match.group(1)
        if href.startswith("/"):
            return f"https://allegro.pl{href}"
        return href
    
    # Alternatywnie - zbuduj z offer_id
    offer_id = extract_offer_id(base_url)
    if offer_id:
        # Probuj wyciagnac slug produktu
        slug_match = re.search(r'/oferta/([^/]+)-\d+', base_url)
        if slug_match:
            slug = slug_match.group(1)
            return f"https://allegro.pl/oferty-produktu/{slug}-{offer_id}"
    
    return None


def parse_listing_store_state(html: str) -> List[Dict[str, Any]]:
    """Parsuje __listing_StoreState z HTML strony porownania."""
    # Szukaj JSON w script tags
    match = re.search(r'__listing_StoreState\s*=\s*({.+?});\s*</script>', html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get("items", {}).get("elements", [])
        except json.JSONDecodeError:
            pass
    
    # Alternatywnie - szukaj w application/json script
    for script_match in re.finditer(r'<script[^>]*type="application/json"[^>]*>(.+?)</script>', html, re.DOTALL):
        try:
            data = json.loads(script_match.group(1))
            if "__listing_StoreState" in data:
                return data["__listing_StoreState"].get("items", {}).get("elements", [])
        except (json.JSONDecodeError, KeyError):
            continue
    
    return []


def scrape_allegro_stealth(
    url: str,
    max_delivery_days: int = MAX_DELIVERY_DAYS,
    proxies: Optional[Dict[str, str]] = None,
    use_oxylabs: bool = True,
) -> ScrapingResult:
    """
    Scrapuje ceny konkurentow z Allegro uzywajac stealth-requests.
    
    Args:
        url: URL oferty Allegro
        max_delivery_days: Max dni dostawy (filtruje wolne)
        proxies: Opcjonalne proxy {"http": "...", "https": "..."}
        use_oxylabs: Uzyj Oxylabs Web Unblocker (domyslnie True)
    
    Returns:
        ScrapingResult z danymi konkurentow
    """
    if not STEALTH_AVAILABLE:
        return ScrapingResult(
            success=False,
            error="stealth_requests nie zainstalowane. Uruchom: pip install stealth_requests[parsers]"
        )
    
    # Uzyj Oxylabs jesli nie podano innego proxy
    if proxies is None and use_oxylabs:
        proxies = OXYLABS_PROXY
    
    result = ScrapingResult(success=False)
    
    try:
        # Uzywamy StealthSession dla utrzymania Referer
        with StealthSession() as session:
            # Krok 1: Pobierz strone oferty
            print(f"[1/4] Pobieranie strony oferty...")
            resp = session.get(url, retry=2, proxies=proxies)
            
            if resp.status_code != 200:
                result.error = f"HTTP {resp.status_code} dla strony oferty"
                return result
            
            html = resp.text
            
            # Sprawdz blokade DataDome
            if "captcha-delivery.com" in html or len(html) < 10000:
                result.error = "Strona zablokowana przez DataDome (brak JS)"
                return result
            
            # Krok 2: Znajdz URL porownania
            print(f"[2/4] Szukanie URL porownania...")
            comparison_url = extract_comparison_url(html, url)
            
            if not comparison_url:
                result.error = "Nie znaleziono linku do porownania ofert"
                return result
            
            print(f"     Znaleziono: {comparison_url}")
            
            # Krok 3: Pobierz strone porownania
            print(f"[3/4] Pobieranie strony porownania...")
            comp_resp = session.get(comparison_url, retry=2, proxies=proxies)
            
            if comp_resp.status_code != 200:
                result.error = f"HTTP {comp_resp.status_code} dla strony porownania"
                return result
            
            comp_html = comp_resp.text
            
            if "captcha-delivery.com" in comp_html or len(comp_html) < 5000:
                result.error = "Strona porownania zablokowana"
                return result
            
            # Krok 4: Parsuj oferty
            print(f"[4/4] Parsowanie ofert...")
            elements = parse_listing_store_state(comp_html)
            
            if not elements:
                result.error = "Nie znaleziono danych ofert w HTML"
                return result
            
            print(f"     Znaleziono {len(elements)} ofert")
            
            # Przetwarzaj oferty
            offers = []
            for el in elements:
                seller = el.get("seller", {})
                price_info = el.get("price", {}).get("mainPrice", {}) or el.get("price", {})
                
                # Dostawa
                delivery = el.get("shipping", {}).get("delivery", {})
                delivery_label = delivery.get("label", {}).get("text", "")
                
                # Alternatywnie sprawdz summary labels
                if not delivery_label:
                    labels = el.get("shipping", {}).get("summary", {}).get("labels", [])
                    for lbl in labels:
                        txt = lbl.get("text", "")
                        if "dostawa" in txt.lower() or "dni" in txt.lower():
                            if "od" not in txt.lower() or "zl" not in txt.lower():
                                delivery_label = txt
                                break
                
                try:
                    price = float(price_info.get("amount", 0))
                except (ValueError, TypeError):
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
            filtered = [
                o for o in offers 
                if o.delivery_days is None or o.delivery_days <= max_delivery_days
            ]
            
            # Znajdz moja oferte
            my_offer = next(
                (o for o in filtered if o.seller.lower() == MY_SELLER.lower()),
                None
            )
            if my_offer:
                result.my_price = my_offer.price
            
            # Konkurenci (bez mojej oferty)
            competitors = [o for o in filtered if o.seller.lower() != MY_SELLER.lower()]
            competitors.sort(key=lambda x: x.price)
            
            result.competitors = competitors
            result.total_offers = len(filtered)
            
            if competitors:
                result.cheapest = competitors[0]
                if result.my_price:
                    result.price_diff = round(result.my_price - competitors[0].price, 2)
            
            result.success = True
            return result
            
    except Exception as e:
        result.error = f"Blad: {str(e)}"
        return result


def format_result(result: ScrapingResult) -> str:
    """Formatuje wynik do wyswietlenia."""
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
        if result.price_diff:
            sign = "+" if result.price_diff > 0 else ""
            lines.append(f"  Roznica: {sign}{result.price_diff} PLN")
    
    if result.competitors:
        lines.append("\n--- Wszyscy konkurenci ---")
        for c in result.competitors[:15]:  # Max 15
            days = f"{c.delivery_days}d" if c.delivery_days is not None else "?"
            super_mark = " [SS]" if c.is_super_seller else ""
            lines.append(f"  {c.seller:25} | {c.price:>8.2f} PLN | {days:>4}{super_mark}")
        
        if len(result.competitors) > 15:
            lines.append(f"  ... i {len(result.competitors) - 15} wiecej")
    
    return "\n".join(lines)


def test_scraper():
    """Test scrapera na przykladowym URL."""
    test_url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323"
    
    print("=" * 60)
    print("STEALTH-REQUESTS SCRAPER TEST")
    print("=" * 60)
    print(f"URL: {test_url}")
    print()
    
    # Najpierw bez proxy (curl_cffi)
    print("Test 1: bez proxy (czysty curl_cffi)...")
    result = scrape_allegro_stealth(test_url, use_oxylabs=False)
    
    if not result.success:
        print(f"Blad: {result.error}")
        print("\nTest 2: z Oxylabs proxy...")
        result = scrape_allegro_stealth(test_url, use_oxylabs=True)
    
    print(format_result(result))
    
    return result.success


def main():
    """Punkt wejscia CLI."""
    if len(sys.argv) < 2:
        print("Uzycie:")
        print("  python stealth_requests_scraper.py <allegro_url>")
        print("  python stealth_requests_scraper.py --test")
        print()
        print("Instalacja wymaganych pakietow:")
        print("  pip install stealth_requests[parsers]")
        return
    
    if sys.argv[1] == "--test":
        success = test_scraper()
        sys.exit(0 if success else 1)
    
    url = sys.argv[1]
    result = scrape_allegro_stealth(url)
    
    if result.success:
        # JSON output
        output = {
            "success": True,
            "my_price": result.my_price,
            "total_offers": result.total_offers,
            "competitor_count": len(result.competitors),
            "cheapest": result.cheapest.to_dict() if result.cheapest else None,
            "price_diff": result.price_diff,
            "competitors": [c.to_dict() for c in result.competitors],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"success": False, "error": result.error}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
