"""Operacje przetwarzania pozycji raportu cenowego."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import distinct, func


logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 5


def get_active_offers_count() -> int:
    """Pobierz liczbę aktywnych ofert Allegro."""
    try:
        from ..db import get_session
        from ..models import AllegroOffer

        with get_session() as session:
            return (
                session.query(AllegroOffer)
                .filter(AllegroOffer.publication_status == "ACTIVE")
                .count()
            )
    except Exception as exc:
        logger.error("Blad pobierania liczby ofert: %s", exc)
        return 0


def create_new_report() -> int:
    """Utwórz nowy raport cenowy w bazie."""
    from ..db import get_session
    from ..models import AllegroOffer, PriceReport

    with get_session() as session:
        total_offers = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.publication_status == "ACTIVE")
            .count()
        )

        report = PriceReport(
            status="pending",
            items_total=total_offers,
            items_checked=0,
        )
        session.add(report)
        session.commit()

        logger.info("Utworzono raport #%s dla %s ofert", report.id, total_offers)
        return report.id


def count_checked_offers(session, report_id: int) -> int:
    """Zwróć liczbę unikalnych ofert sprawdzonych w raporcie."""
    from ..models import PriceReportItem

    return (
        session.query(func.count(distinct(PriceReportItem.offer_id)))
        .filter(PriceReportItem.report_id == report_id)
        .scalar()
        or 0
    )


def sync_report_progress(session, report_id: int, status: str = "running") -> None:
    """Zsynchronizuj licznik postępu z faktyczną liczbą unikalnych ofert."""
    from ..models import PriceReport

    session.flush()
    report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
    if report:
        report.items_checked = count_checked_offers(session, report_id)
        if status:
            report.status = status


def get_or_create_report_item(session, report_id: int, offer_id: str):
    """Zwróć wpis raportu dla oferty i usuń ewentualne duplikaty."""
    from ..models import PriceReportItem

    items = (
        session.query(PriceReportItem)
        .filter(
            PriceReportItem.report_id == report_id,
            PriceReportItem.offer_id == offer_id,
        )
        .order_by(PriceReportItem.id.desc())
        .all()
    )

    if items:
        keeper = items[0]
        for duplicate in items[1:]:
            session.delete(duplicate)
        return keeper, False, max(0, len(items) - 1)

    item = PriceReportItem(report_id=report_id, offer_id=offer_id)
    session.add(item)
    return item, True, 0


def mark_sibling_offers(report_id: int) -> int:
    """Oznacz droższe oferty tego samego wariantu jako niewymagające scrapingu."""
    from ..db import get_session
    from ..models import AllegroOffer, PriceReportItem

    marked = 0
    with get_session() as session:
        checked_offer_ids = {
            row[0]
            for row in session.query(PriceReportItem.offer_id)
            .filter(PriceReportItem.report_id == report_id)
            .all()
        }

        active_offers = (
            session.query(AllegroOffer)
            .filter(
                AllegroOffer.publication_status == "ACTIVE",
                AllegroOffer.product_size_id != None,
            )
            .all()
        )

        groups = {}
        for offer in active_offers:
            groups.setdefault(offer.product_size_id, []).append(offer)

        for product_size_id, offers in groups.items():
            if len(offers) < 2:
                continue

            offers_sorted = sorted(
                offers,
                key=lambda offer: float(offer.price) if offer.price else 999999,
            )
            cheapest = offers_sorted[0]

            for offer in offers_sorted[1:]:
                if offer.offer_id in checked_offer_ids:
                    continue

                cheapest_price = float(cheapest.price) if cheapest.price else None
                our_price = float(offer.price) if offer.price else None

                if our_price and cheapest_price and our_price > cheapest_price:
                    session.add(
                        PriceReportItem(
                            report_id=report_id,
                            offer_id=offer.offer_id,
                            product_name=offer.title,
                            our_price=Decimal(str(our_price)),
                            competitor_price=None,
                            competitor_seller=None,
                            is_cheapest=False,
                            our_position=None,
                            total_offers=None,
                            error=None,
                        )
                    )
                    marked += 1
                    logger.info(
                        "Inna OK: %s (%s zl) - tansza siostra %s (%s zl) na product_size=%s",
                        offer.offer_id,
                        our_price,
                        cheapest.offer_id,
                        cheapest_price,
                        product_size_id,
                    )

        if marked > 0:
            sync_report_progress(session, report_id)
            session.commit()
            logger.info("Oznaczono %s ofert jako 'Inna OK' w raporcie #%s", marked, report_id)

    return marked


def get_unchecked_offers(report_id: int, limit: int = DEFAULT_BATCH_SIZE) -> list[dict]:
    """Pobierz oferty do sprawdzenia, aktualizując najpierw ich cenę z Allegro."""
    from ..allegro_api.offers import get_offer_details
    from ..db import get_session
    from ..models import AllegroOffer, PriceReportItem

    with get_session() as session:
        checked_offer_ids = (
            session.query(PriceReportItem.offer_id)
            .filter(PriceReportItem.report_id == report_id)
            .scalar_subquery()
        )

        offers = (
            session.query(AllegroOffer)
            .filter(
                AllegroOffer.publication_status == "ACTIVE",
                ~AllegroOffer.offer_id.in_(checked_offer_ids),
            )
            .limit(limit)
            .all()
        )

        result_offers = []
        for offer in offers:
            current_price = float(offer.price) if offer.price else None

            try:
                offer_details = get_offer_details(offer.offer_id)
                if offer_details.get("success") and offer_details.get("price"):
                    new_price = offer_details["price"]
                    if new_price != offer.price:
                        logger.info(
                            "Aktualizacja ceny oferty %s: %s -> %s",
                            offer.offer_id,
                            offer.price,
                            new_price,
                        )
                        offer.price = new_price
                        session.commit()
                        current_price = float(new_price)
            except Exception as exc:
                logger.warning(
                    "Nie udalo sie zaktualizowac ceny oferty %s: %s",
                    offer.offer_id,
                    exc,
                )

            result_offers.append(
                {
                    "offer_id": offer.offer_id,
                    "title": offer.title,
                    "price": current_price,
                    "product_size_id": offer.product_size_id,
                }
            )

        return result_offers


def save_report_item(report_id: int, result: dict) -> None:
    """Zapisz wynik sprawdzenia oferty do raportu."""
    from ..db import get_session
    from ..models import AllegroOffer, PriceReportItem

    with get_session() as session:
        item, created, removed_duplicates = get_or_create_report_item(
            session,
            report_id,
            result["offer_id"],
        )
        if removed_duplicates:
            logger.warning(
                "Usunieto %s duplikatow wpisu raportu dla report=%s offer=%s",
                removed_duplicates,
                report_id,
                result["offer_id"],
            )

        our_price = Decimal(str(result["our_price"])) if result["our_price"] else None
        competitor_price = None
        competitor_seller = None
        competitor_url = None
        is_cheapest = True
        price_difference = None

        competitor_is_super = None
        if result["cheapest"]:
            competitor_price = Decimal(str(result["cheapest"]["price"]))
            competitor_seller = result["cheapest"]["seller"]
            competitor_url = result["cheapest"]["url"]
            competitor_is_super = result["cheapest"].get("is_super_seller", False)

            if our_price:
                is_cheapest = our_price <= competitor_price
                price_difference = float(our_price - competitor_price)

        item.product_name = result["title"]
        item.our_price = our_price
        item.competitor_price = competitor_price
        item.competitor_seller = competitor_seller
        item.competitor_url = competitor_url
        item.is_cheapest = is_cheapest
        item.price_difference = price_difference
        item.our_position = result["my_position"]
        item.total_offers = result["competitors_count"] + 1
        item.competitors_all_count = result.get("competitors_all_count")
        item.competitor_is_super_seller = competitor_is_super
        item.error = result["error"]
        item.checked_at = datetime.now()

        siblings = result.get("our_siblings", [])
        siblings_marked = 0
        checked_product_size_id = result.get("product_size_id")
        if our_price and siblings:
            for sibling in siblings:
                sibling_id = sibling["offer_id"]
                sibling_price = sibling["price"]

                if sibling_id == result["offer_id"]:
                    continue
                if sibling_price is None or float(our_price) >= sibling_price:
                    continue

                sibling_offer = (
                    session.query(AllegroOffer)
                    .filter(AllegroOffer.offer_id == sibling_id)
                    .first()
                )

                if not sibling_offer:
                    continue

                if sibling_offer.product_size_id != checked_product_size_id:
                    logger.info(
                        "Pominieto siostre CDP: %s (ps_id=%s) - inny wariant niz %s (ps_id=%s)",
                        sibling_id,
                        sibling_offer.product_size_id,
                        result["offer_id"],
                        checked_product_size_id,
                    )
                    continue

                if sibling_price and float(our_price) > 0:
                    price_ratio = sibling_price / float(our_price)
                    if price_ratio > 1.20:
                        logger.info(
                            "Pominieto siostre CDP: %s (%s zl) - roznica cenowa %.0f%% od %s (%s zl) (prog 20%% - prawdopodobnie inny wariant)",
                            sibling_id,
                            sibling_price,
                            (price_ratio - 1) * 100,
                            result["offer_id"],
                            float(our_price),
                        )
                        continue

                existing_siblings = (
                    session.query(PriceReportItem)
                    .filter(
                        PriceReportItem.report_id == report_id,
                        PriceReportItem.offer_id == sibling_id,
                    )
                    .order_by(PriceReportItem.id.desc())
                    .all()
                )

                existing_sibling_item = existing_siblings[0] if existing_siblings else None
                for duplicate in existing_siblings[1:]:
                    session.delete(duplicate)

                if existing_sibling_item:
                    if existing_sibling_item.competitor_price is not None:
                        existing_sibling_item.competitor_price = None
                        existing_sibling_item.competitor_seller = None
                        existing_sibling_item.competitor_url = None
                        existing_sibling_item.competitor_is_super_seller = None
                        existing_sibling_item.is_cheapest = False
                        existing_sibling_item.our_position = None
                        existing_sibling_item.total_offers = None
                        existing_sibling_item.price_difference = None
                        existing_sibling_item.error = None
                        existing_sibling_item.checked_at = datetime.now()
                        logger.info(
                            "Inna OK (CDP update): %s (%s zl) - tansza siostra %s (%s zl) wykryta w dialogu",
                            sibling_id,
                            sibling_price,
                            result["offer_id"],
                            float(our_price),
                        )
                    continue

                sibling_title = sibling_offer.title if sibling_offer else f"Siostra oferty {result['offer_id']}"

                sibling_item, _, removed_sibling_duplicates = get_or_create_report_item(
                    session,
                    report_id,
                    sibling_id,
                )
                if removed_sibling_duplicates:
                    logger.warning(
                        "Usunieto %s duplikatow siostrzanego wpisu dla report=%s offer=%s",
                        removed_sibling_duplicates,
                        report_id,
                        sibling_id,
                    )
                sibling_item.product_name = sibling_title
                sibling_item.our_price = Decimal(str(sibling_price))
                sibling_item.competitor_price = None
                sibling_item.competitor_seller = None
                sibling_item.competitor_url = None
                sibling_item.competitor_is_super_seller = None
                sibling_item.is_cheapest = False
                sibling_item.our_position = None
                sibling_item.total_offers = None
                sibling_item.price_difference = None
                sibling_item.error = None
                sibling_item.checked_at = datetime.now()
                siblings_marked += 1
                logger.info(
                    "Inna OK (CDP): %s (%s zl) - tansza siostra %s (%s zl) wykryta w dialogu",
                    sibling_id,
                    sibling_price,
                    result["offer_id"],
                    float(our_price),
                )

        if not created and siblings_marked:
            logger.debug(
                "Zaktualizowano istniejący wpis raportu %s i oznaczono %s siostrzanych ofert",
                result["offer_id"],
                siblings_marked,
            )

        sync_report_progress(session, report_id)
        session.commit()


def finalize_report(report_id: int) -> None:
    """Oznacz raport jako zakończony."""
    from ..db import get_session
    from ..models import PriceReport, PriceReportItem

    with get_session() as session:
        report = session.query(PriceReport).filter(PriceReport.id == report_id).first()
        if report:
            error_count = (
                session.query(PriceReportItem)
                .filter(
                    PriceReportItem.report_id == report_id,
                    PriceReportItem.error != None,
                )
                .count()
            )
            if error_count > 0:
                report.status = "completed_with_errors"
                logger.warning(
                    "Raport #%s zakonczony z %s bledami - status: completed_with_errors",
                    report_id,
                    error_count,
                )
            else:
                report.status = "completed"
            report.completed_at = datetime.now()
            session.commit()
            logger.info("Raport #%s zakonczony (bledy: %s)", report_id, error_count)


__all__ = [
    "count_checked_offers",
    "create_new_report",
    "finalize_report",
    "get_active_offers_count",
    "get_or_create_report_item",
    "get_unchecked_offers",
    "mark_sibling_offers",
    "save_report_item",
    "sync_report_progress",
]