"""CLI dla scrapera cen Allegro."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from .checker import check_offer_price
from .config import CDP_HOST, CDP_PORT, MAX_DELIVERY_DAYS
from .models import PriceCheckResult

logger = logging.getLogger(__name__)


def print_result(result: PriceCheckResult) -> None:
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
    for index, competitor in enumerate(result.competitors, 1):
        days = f" [{competitor.delivery_days}d]" if competitor.delivery_days is not None else ""
        condition = f" [{competitor.condition}]" if competitor.condition else ""
        print(
            f"  {index}. {competitor.seller}: {competitor.price:.2f} zl "
            f"({competitor.price_with_delivery:.2f} zl z dostawa){days}{condition}"
        )

    if result.cheapest_competitor:
        competitor = result.cheapest_competitor
        days_info = f" (dostawa {competitor.delivery_days}d)" if competitor.delivery_days is not None else ""
        print(f"\nNajtansza konkurencja: {competitor.seller} - {competitor.price:.2f} zl{days_info}")
        if competitor.offer_url:
            print(f"Link: {competitor.offer_url}")

        if result.my_price:
            diff = result.my_price - competitor.price
            if diff > 0:
                print(f"Jestem DROZSZY o {diff:.2f} zl")
            elif diff < 0:
                print(f"Jestem TANSZY o {-diff:.2f} zl")
            else:
                print("Mam taka sama cene")


async def check_offers_from_db(
    cdp_host: str,
    cdp_port: int,
    limit: int = 10,
    max_delivery_days: int = MAX_DELIVERY_DAYS,
) -> None:
    """Sprawdza oferty z bazy danych."""
    try:
        from magazyn.config import settings
        from magazyn.db import configure_engine, get_session
        from magazyn.models.allegro import AllegroOffer, AllegroPriceHistory

        configure_engine(settings.DB_PATH)
    except ImportError as exc:
        logger.error("Nie mozna zaimportowac modulow magazyn: %s", exc)
        logger.error("Uruchom z katalogu retrievershop-suite lub ustaw PYTHONPATH")
        return

    with get_session() as session:
        offers = session.query(AllegroOffer).filter(AllegroOffer.publication_status == "ACTIVE").limit(limit).all()
        logger.info("Znaleziono %s aktywnych ofert (filtr dostawy: max %s dni)", len(offers), max_delivery_days)

        for index, offer in enumerate(offers, 1):
            print(f"\n[{index}/{len(offers)}] {offer.title[:50]}...")
            result = await check_offer_price(
                offer.offer_id,
                offer.title,
                float(offer.price) if offer.price else None,
                cdp_host,
                cdp_port,
                max_delivery_days,
            )
            print_result(result)

            if result.success and result.cheapest_competitor:
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
                logger.info(
                    "Zapisano do historii: %s @ %s",
                    result.cheapest_competitor.seller,
                    result.cheapest_competitor.price,
                )

            await asyncio.sleep(3)

        session.commit()
        logger.info("Zapisano wszystkie wyniki do bazy")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper cen konkurencji Allegro przez CDP")
    parser.add_argument("--offer-id", help="ID oferty do sprawdzenia")
    parser.add_argument("--title", default="", help="Tytul oferty (opcjonalny)")
    parser.add_argument("--my-price", type=float, help="Moja cena (opcjonalna)")
    parser.add_argument("--check-db", action="store_true", help="Sprawdz oferty z bazy danych")
    parser.add_argument("--limit", type=int, default=10, help="Limit ofert przy --check-db")
    parser.add_argument("--cdp-host", default=CDP_HOST, help="Host CDP")
    parser.add_argument("--cdp-port", type=int, default=CDP_PORT, help="Port CDP")
    parser.add_argument(
        "--max-delivery-days",
        type=int,
        default=MAX_DELIVERY_DAYS,
        help=f"Maksymalna liczba dni dostawy (domyslnie {MAX_DELIVERY_DAYS}, filtruje chinskich sprzedawcow)",
    )
    parser.add_argument("--json", action="store_true", help="Wyswietl wynik jako JSON")

    args = parser.parse_args()
    if args.offer_id:
        result = await check_offer_price(
            args.offer_id,
            args.title,
            args.my_price,
            args.cdp_host,
            args.cdp_port,
            args.max_delivery_days,
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