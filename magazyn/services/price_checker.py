"""
Serwis sprawdzania cen konkurencji na Allegro.

Wyodrebniony z allegro.py dla lepszej organizacji kodu.
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..models import AllegroOffer, Product, ProductSize
from ..allegro_scraper import (
    AllegroScrapeError,
    fetch_competitors_for_offer,
    parse_price_amount,
)


logger = logging.getLogger(__name__)


@dataclass
class PriceCheckResult:
    """Wynik sprawdzania ceny dla pojedynczej oferty."""
    offer_id: str
    title: str
    label: str
    own_price: Optional[str]
    competitor_price: Optional[str]
    is_lowest: Optional[bool]
    error: Optional[str]
    competitor_offer_url: Optional[str]


@dataclass
class DebugContext:
    """Kontekst debugowania dla sprawdzania cen."""
    steps: List[Dict[str, str]] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    log_callback: Optional[Callable[[str, str], None]] = None
    screenshot_callback: Optional[Callable[[dict], None]] = None
    
    def record(self, label: str, value: object) -> None:
        """Zapisuje krok debugowania."""
        formatted = self._format_value(value)
        self.steps.append({"label": label, "value": formatted})
        
        if formatted:
            line = f"{label}: {formatted}"
        else:
            line = label
        self.logs.append(line)
        
        if self.log_callback:
            self.log_callback(label, formatted)
    
    @staticmethod
    def _format_value(value: object) -> str:
        """Formatuje wartosc do wyswietlenia."""
        if value is None:
            return "None"
        if isinstance(value, (dict, list, tuple)):
            try:
                return json.dumps(value, ensure_ascii=False, indent=2, default=str)
            except TypeError:
                return str(value)
        return str(value)


def _format_decimal(value: Optional[Decimal]) -> Optional[str]:
    """Formatuje Decimal do stringa."""
    if value is None:
        return None
    return f"{value:.2f}"


class PriceCheckerService:
    """
    Serwis do sprawdzania cen konkurencji na Allegro.
    
    Uzycie:
        service = PriceCheckerService()
        results = service.check_all_prices(debug_context)
    """
    
    def __init__(self, db: Optional[Session] = None):
        """
        Args:
            db: Opcjonalna sesja SQLAlchemy (jesli None, utworzy wlasna)
        """
        self._db = db
        self._external_db = db is not None
    
    def check_all_prices(
        self,
        debug: Optional[DebugContext] = None
    ) -> List[PriceCheckResult]:
        """
        Sprawdza ceny konkurencji dla wszystkich powiazanych ofert.
        
        Args:
            debug: Opcjonalny kontekst debugowania
            
        Returns:
            Lista wynikow sprawdzania cen
        """
        debug = debug or DebugContext()
        
        # Pobierz oferty z DB
        offers = self._get_linked_offers(debug)
        if not offers:
            return []
        
        # Grupuj oferty po kodzie kreskowym
        offers_by_barcode, offers_without_barcode = self._group_offers_by_barcode(offers, debug)
        
        # Sprawdz ceny
        results_by_offer = self._check_prices_batch(offers_by_barcode, debug)
        results_by_offer = self._check_prices_fallback(
            offers_by_barcode, 
            offers_without_barcode, 
            results_by_offer, 
            debug
        )
        
        # Zbuduj wyniki
        return self._build_results(offers, results_by_offer)
    
    def _get_linked_offers(self, debug: DebugContext) -> List[Dict[str, Any]]:
        """Pobiera powiazane oferty z bazy danych."""
        if self._external_db:
            db = self._db
            return self._query_offers(db, debug)
        else:
            with get_session() as db:
                return self._query_offers(db, debug)
    
    def _query_offers(self, db: Session, debug: DebugContext) -> List[Dict[str, Any]]:
        """Wykonuje zapytanie o oferty."""
        rows = (
            db.query(AllegroOffer, ProductSize, Product)
            .outerjoin(ProductSize, AllegroOffer.product_size_id == ProductSize.id)
            .outerjoin(
                Product,
                or_(
                    Product.id == AllegroOffer.product_id,
                    Product.id == ProductSize.product_id,
                ),
            )
            .filter(
                or_(
                    AllegroOffer.product_size_id.isnot(None),
                    AllegroOffer.product_id.isnot(None),
                )
            )
            .all()
        )
        
        offers = []
        for offer, size, product in rows:
            product_for_label = product or (size.product if size else None)
            if not product_for_label:
                continue
            
            barcodes: List[str] = []
            if size:
                name_parts = [product_for_label.name]
                if product_for_label.color:
                    name_parts.append(product_for_label.color)
                label = " ".join(name_parts) + f" - {size.size}"
                if size.barcode:
                    barcodes.append(size.barcode)
            else:
                name_parts = [product_for_label.name]
                if product_for_label.color:
                    name_parts.append(product_for_label.color)
                label = " ".join(name_parts)
                related_sizes = list(product_for_label.sizes or [])
                for related_size in related_sizes:
                    if related_size.barcode:
                        barcodes.append(related_size.barcode)
            
            offers.append({
                "offer_id": offer.offer_id,
                "title": offer.title,
                "price": Decimal(offer.price).quantize(Decimal("0.01")),
                "barcodes": barcodes,
                "label": label,
                "product_size_id": offer.product_size_id,
            })
        
        debug.record("Liczba powiazanych ofert", len(offers))
        return offers
    
    def _group_offers_by_barcode(
        self, 
        offers: List[Dict], 
        debug: DebugContext
    ) -> Tuple[Dict[str, List[Dict]], List[Dict]]:
        """Grupuje oferty po kodzie kreskowym."""
        offers_by_barcode: Dict[str, List[Dict]] = {}
        offers_without_barcode: List[Dict] = []
        
        for offer in offers:
            barcode_list = [code for code in offer["barcodes"] if code]
            if barcode_list and offer["product_size_id"] is not None:
                for barcode in barcode_list:
                    offers_by_barcode.setdefault(barcode, []).append(offer)
            else:
                offers_without_barcode.append(offer)
        
        debug.record(
            "Liczba grup kodow kreskowych",
            {"grupy": len(offers_by_barcode), "bez_kodu": len(offers_without_barcode)}
        )
        
        if offers_without_barcode:
            debug.record(
                "Oferty bez kodu kreskowego",
                [
                    {
                        "offer_id": offer["offer_id"],
                        "title": offer["title"],
                        "barcodes": offer["barcodes"],
                    }
                    for offer in offers_without_barcode
                ]
            )
        
        return offers_by_barcode, offers_without_barcode
    
    def _check_prices_batch(
        self,
        offers_by_barcode: Dict[str, List[Dict]],
        debug: DebugContext
    ) -> Dict[str, Dict[str, Any]]:
        """Sprawdza ceny przez batch scraper (scraper_tasks)."""
        results_by_offer: Dict[str, Dict[str, Any]] = {}
        all_eans = list(offers_by_barcode.keys())
        
        if not all_eans:
            return results_by_offer
        
        with get_session() as session:
            debug.record("Tworzenie zadan scrapowania", {"count": len(all_eans), "eans": all_eans})
            
            # Utworz zadania scrapowania
            for ean in all_eans:
                session.execute(
                    text("""
                    INSERT INTO scraper_tasks (ean, status, created_at)
                    VALUES (:ean, 'pending', CURRENT_TIMESTAMP)
                    """),
                    {"ean": ean}
                )
                session.commit()
            
            # Sprawdz istniejace wyniki
            placeholders = ",".join([f":ean{i}" for i in range(len(all_eans))])
            params = {f"ean{i}": ean for i, ean in enumerate(all_eans)}
            
            result_query = session.execute(
                text(f"""
                SELECT ean, price, url, error
                FROM scraper_tasks
                WHERE ean IN ({placeholders})
                  AND status = 'done'
                  AND completed_at > datetime('now', '-1 hour')
                ORDER BY completed_at DESC
                """),
                params
            )
            rows = result_query.fetchall()
            
            # Uzyj najnowszych wynikow
            ean_results = {}
            for row in rows:
                ean = row[0]
                if ean not in ean_results:
                    ean_results[ean] = {
                        "price": row[1],
                        "url": row[2],
                        "error": row[3]
                    }
            
            # Mapuj wyniki do ofert
            for barcode, grouped_offers in offers_by_barcode.items():
                result = ean_results.get(barcode)
                
                if result and result["price"]:
                    for offer in grouped_offers:
                        results_by_offer[offer["offer_id"]] = {
                            "competitor_price": result["price"],
                            "competitor_url": result["url"],
                            "error": None,
                        }
                    debug.record(
                        "Najnizsza cena dla EAN (z cache)",
                        {"ean": barcode, "price": _format_decimal(result["price"])}
                    )
        
        return results_by_offer
    
    def _check_prices_fallback(
        self,
        offers_by_barcode: Dict[str, List[Dict]],
        offers_without_barcode: List[Dict],
        results_by_offer: Dict[str, Dict[str, Any]],
        debug: DebugContext
    ) -> Dict[str, Dict[str, Any]]:
        """Sprawdza ceny przez Selenium (fallback)."""
        
        def process_competitor_lookup(
            reference_offer: Dict,
            barcode: Optional[str],
            target_offers: List[Dict]
        ) -> None:
            """Przetwarza pojedyncze sprawdzenie konkurencji."""
            offer_id = reference_offer["offer_id"]
            offer_url = f"https://allegro.pl/oferta/{offer_id}"
            
            context = {"offer_id": offer_id, "url": offer_url}
            if barcode:
                context["barcode"] = barcode
                debug.record("Sprawdzanie ofert Allegro dla kodu kreskowego", context)
            else:
                debug.record("Sprawdzanie oferty Allegro", context)
            
            competitor_min_price: Optional[Decimal] = None
            competitor_min_url: Optional[str] = None
            error: Optional[str] = None
            
            # Sprobuj lokalny scraper
            if settings.ALLEGRO_SCRAPER_API_URL:
                debug.record("Uzywanie lokalnego scrapera", {"url": settings.ALLEGRO_SCRAPER_API_URL})
                try:
                    from ..allegro import fetch_price_via_local_scraper
                    price = fetch_price_via_local_scraper(offer_url)
                    if price is not None:
                        competitor_min_price = price
                        competitor_min_url = offer_url
                        debug.record(
                            "Cena z lokalnego scrapera",
                            {"price": _format_decimal(price), "url": offer_url}
                        )
                    else:
                        debug.record("Lokalny scraper nie zwrocil ceny", {})
                except Exception as exc:
                    debug.record("Blad lokalnego scrapera", {"error": str(exc)})
            
            # Fallback do Selenium
            if competitor_min_price is None:
                competitor_min_price, competitor_min_url, error = self._check_via_selenium(
                    offer_id, offer_url, barcode, debug
                )
            
            if competitor_min_price is not None:
                error = None
            
            for offer in target_offers:
                results_by_offer[offer["offer_id"]] = {
                    "competitor_price": competitor_min_price,
                    "competitor_url": competitor_min_url,
                    "error": error,
                }
        
        # Przetwarzaj grupy z barcode ktore nie maja wynikow z batch
        for barcode, grouped_offers in offers_by_barcode.items():
            first_offer_id = grouped_offers[0]["offer_id"]
            if first_offer_id in results_by_offer:
                debug.record(
                    "Grupa ofert juz przetworzona przez batch scraper",
                    {"barcode": barcode, "offers": len(grouped_offers)}
                )
                continue
            
            debug.record(
                "Grupa ofert dla kodu kreskowego - fallback Selenium",
                {
                    "barcode": barcode,
                    "offers": [
                        {"offer_id": o["offer_id"], "price": _format_decimal(o["price"])}
                        for o in grouped_offers
                    ],
                }
            )
            process_competitor_lookup(grouped_offers[0], barcode, grouped_offers)
        
        # Przetwarzaj oferty bez barcode
        for offer in offers_without_barcode:
            process_competitor_lookup(offer, None, [offer])
        
        return results_by_offer
    
    def _check_via_selenium(
        self,
        offer_id: str,
        offer_url: str,
        barcode: Optional[str],
        debug: DebugContext
    ) -> Tuple[Optional[Decimal], Optional[str], Optional[str]]:
        """Sprawdza cene przez Selenium scraper."""
        competitor_min_price: Optional[Decimal] = None
        competitor_min_url: Optional[str] = None
        error: Optional[str] = None
        
        def stream_scrape_log(message: str) -> None:
            log_context = {"offer_id": offer_id, "message": message}
            if barcode:
                log_context["barcode"] = barcode
            debug.record("Log Selenium", log_context)
        
        scraper_callback = stream_scrape_log if debug.log_callback else None
        
        def stream_screenshot(image: bytes, stage: str) -> None:
            if debug.screenshot_callback is None:
                return
            payload = {
                "offer_id": offer_id,
                "stage": stage,
                "image": base64.b64encode(image).decode("ascii"),
            }
            if barcode:
                payload["barcode"] = barcode
            debug.screenshot_callback(payload)
        
        screenshot_handler = stream_screenshot if debug.screenshot_callback else None
        
        try:
            competitor_offers, scrape_logs = fetch_competitors_for_offer(
                offer_id,
                stop_seller=settings.ALLEGRO_SELLER_NAME,
                log_callback=scraper_callback,
                screenshot_callback=screenshot_handler,
            )
        except AllegroScrapeError as exc:
            error = str(exc)
            debug.record(
                "Blad pobierania ofert Allegro",
                {"offer_id": offer_id, "url": offer_url, "error": str(exc), "barcode": barcode}
            )
            competitor_offers = []
            scrape_logs = exc.logs
        except Exception as exc:
            error = str(exc)
            debug.record(
                "Blad pobierania ofert Allegro",
                {"offer_id": offer_id, "url": offer_url, "error": str(exc), "barcode": barcode}
            )
            competitor_offers = []
            scrape_logs = []
        
        if not debug.log_callback:
            for entry in scrape_logs:
                debug.record("Log Selenium", {"offer_id": offer_id, "message": entry, "barcode": barcode})
        
        debug.record(
            "Oferty konkurencji - liczba ofert",
            {"offer_id": offer_id, "offers": len(competitor_offers), "barcode": barcode}
        )
        
        for competitor in competitor_offers:
            seller_name = (competitor.seller or "").strip().lower()
            if (
                settings.ALLEGRO_SELLER_NAME
                and seller_name
                and seller_name == settings.ALLEGRO_SELLER_NAME.lower()
            ):
                continue
            price_value = parse_price_amount(competitor.price)
            if price_value is None:
                continue
            if (
                competitor_min_price is None
                or price_value < competitor_min_price
                or (price_value == competitor_min_price and competitor_min_url is None)
            ):
                competitor_min_price = price_value
                competitor_min_url = competitor.url
        
        if barcode:
            debug.record(
                "Najnizsza cena konkurencji dla kodu",
                {"barcode": barcode, "price": _format_decimal(competitor_min_price), "url": competitor_min_url}
            )
        
        return competitor_min_price, competitor_min_url, error
    
    def _build_results(
        self,
        offers: List[Dict],
        results_by_offer: Dict[str, Dict[str, Any]]
    ) -> List[PriceCheckResult]:
        """Buduje liste wynikow."""
        results = []
        
        for offer in offers:
            result = results_by_offer.get(
                offer["offer_id"],
                {"competitor_price": None, "competitor_url": None, "error": None}
            )
            competitor_min = result["competitor_price"]
            
            is_lowest = None
            if offer["price"] is not None:
                if competitor_min is None:
                    is_lowest = True
                else:
                    is_lowest = offer["price"] <= competitor_min
            
            results.append(PriceCheckResult(
                offer_id=offer["offer_id"],
                title=offer["title"],
                label=offer["label"],
                own_price=_format_decimal(offer["price"]),
                competitor_price=_format_decimal(competitor_min),
                is_lowest=is_lowest,
                error=result["error"],
                competitor_offer_url=result["competitor_url"],
            ))
        
        return results


def build_price_checks(
    debug_steps: Optional[List[Dict[str, str]]] = None,
    debug_logs: Optional[List[str]] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
    screenshot_callback: Optional[Callable[[dict], None]] = None,
) -> List[Dict]:
    """
    Funkcja kompatybilnosci wstecznej.
    
    Deleguje do PriceCheckerService.
    """
    debug = DebugContext(
        steps=debug_steps or [],
        logs=debug_logs or [],
        log_callback=log_callback,
        screenshot_callback=screenshot_callback,
    )
    
    service = PriceCheckerService()
    results = service.check_all_prices(debug)
    
    # Konwertuj na stary format dict
    return [
        {
            "offer_id": r.offer_id,
            "title": r.title,
            "label": r.label,
            "own_price": r.own_price,
            "competitor_price": r.competitor_price,
            "is_lowest": r.is_lowest,
            "error": r.error,
            "competitor_offer_url": r.competitor_offer_url,
        }
        for r in results
    ]
