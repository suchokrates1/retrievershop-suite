"""
Stub dla allegro_scraper - zawiera tylko definicje typow uzywane przez inne moduly.

Wlasciwy scraping odbywa sie przez CDP w magazyn/scripts/price_checker_ws.py
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Sequence
import re


class AllegroScrapeError(RuntimeError):
    """Raised when scraping Allegro listings fails."""

    def __init__(self, message: str, logs: Sequence[str] = ()):
        super().__init__(message)
        self.logs = list(logs)


@dataclass(slots=True)
class Offer:
    """Representation of a competitor offer scraped from Allegro."""

    title: str
    price: str
    seller: str
    url: str


def parse_price_amount(price_text: str) -> Optional[Decimal]:
    """
    Parse a price string like '123,45 zl' or '1 234,56 zl' into Decimal.
    
    Returns None if parsing fails.
    """
    if not price_text:
        return None
    
    # Usun 'zl', 'PLN' i biale znaki
    cleaned = re.sub(r'[złzlPLN\s]', '', price_text, flags=re.IGNORECASE)
    # Zamien przecinek na kropke
    cleaned = cleaned.replace(',', '.')
    # Usun spacje jako separatory tysiecy
    cleaned = cleaned.replace(' ', '').replace('\u00a0', '')
    
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def fetch_competitors_for_offer(
    offer_url: str,
    *,
    own_price: Optional[Decimal] = None,
    headless: bool = True,
    cookies_path: Optional[str] = None,
    logs: Optional[List[str]] = None,
) -> List[Offer]:
    """
    Stub - ta funkcja nie jest juz uzywana.
    
    Scraping odbywa sie przez CDP w magazyn/scripts/price_checker_ws.py
    """
    raise AllegroScrapeError(
        "fetch_competitors_for_offer jest przestarzale - uzyj price_checker_ws.py z CDP",
        logs or []
    )
