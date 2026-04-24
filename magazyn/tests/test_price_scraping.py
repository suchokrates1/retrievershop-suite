"""Testy dla poprawek systemu scrapingu i raportow cenowych."""

import pytest
import asyncio
from unittest.mock import MagicMock, patch
from decimal import Decimal
from datetime import date


class _FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 4, 20)


# --- Testy parse_delivery_days ---

def test_parse_delivery_days_jutro():
    with patch("magazyn.scripts.price_checker_ws.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days("dostawa jutro") == 1


def test_parse_delivery_days_pojutrze():
    with patch("magazyn.scripts.price_checker_ws.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days("dostawa pojutrze") == 2


def test_parse_delivery_days_za_dni():
    with patch("magazyn.scripts.price_checker_ws.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days("dostawa za 2-3 dni") == 2


def test_parse_delivery_days_od_chinczyk():
    with patch("magazyn.scripts.price_checker_ws.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        result = parse_delivery_days("dostawa od 14 dni")
        assert result == 99  # Wysoka wartosc = odfiltruj


def test_parse_delivery_days_none():
    with patch("magazyn.scripts.price_checker_ws.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days(None) is None
        assert parse_delivery_days("") is None


def test_parse_delivery_days_dzisiaj():
    with patch("magazyn.scripts.price_checker_ws.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days("dostawa dzisiaj") == 0


# --- Testy CompetitorOffer nowe pola ---

def test_competitor_offer_super_seller():
    from magazyn.scripts.price_checker_ws import CompetitorOffer
    offer = CompetitorOffer(
        seller="TestSeller",
        price=100.0,
        price_with_delivery=108.99,
        is_super_seller=True,
        has_smart=True,
        offer_id="12345678901",
    )
    assert offer.is_super_seller is True
    assert offer.has_smart is True
    assert offer.offer_id == "12345678901"


def test_competitor_offer_defaults():
    from magazyn.scripts.price_checker_ws import CompetitorOffer
    offer = CompetitorOffer(seller="X", price=50.0, price_with_delivery=50.0)
    assert offer.is_super_seller is False
    assert offer.has_smart is False
    assert offer.offer_id is None


# --- Testy PriceCheckResult nowe pola ---

def test_price_check_result_competitors_all_count():
    from magazyn.scripts.price_checker_ws import PriceCheckResult
    result = PriceCheckResult(
        offer_id="123",
        success=True,
        competitors_all_count=15,
    )
    assert result.competitors_all_count == 15


# --- Testy parsowania i filtrowania ofert ---

def test_parse_competitor_articles_parses_condition_and_url():
    from magazyn.scripts.price_checker_ws import parse_competitor_articles

    offers = parse_competitor_articles([
        {
            "index": 0,
            "offerId": "99988877766",
            "offerUrl": "https://allegro.pl/oferta/x-99988877766",
            "ariaPrice": "119,99",
            "text": "Powystawowy\nod\nSuper Sprzedawcy\nWhatsUpDog\n119,99 zł\n119,99 zł z dostawą\nSmart!\ndostawa jutro",
        }
    ])

    assert len(offers) == 1
    assert offers[0].seller == "WhatsUpDog"
    assert offers[0].offer_id == "99988877766"
    assert offers[0].offer_url == "https://allegro.pl/oferta/x-99988877766"
    assert offers[0].condition == "powystawowy"
    assert offers[0].has_smart is True


def test_filter_competitor_offers_excludes_bad_condition_and_delivery():
    from magazyn.scripts.price_checker_ws import CompetitorOffer, filter_competitor_offers

    offers = [
        CompetitorOffer(seller="A", price=100.0, price_with_delivery=100.0, condition="nowy"),
        CompetitorOffer(seller="B", price=99.0, price_with_delivery=99.0, condition="powystawowy"),
        CompetitorOffer(seller="C", price=98.0, price_with_delivery=98.0, delivery_days=5, condition="nowy"),
        CompetitorOffer(seller="D", price=97.0, price_with_delivery=97.0, condition="nowy"),
    ]

    filtered, stats = filter_competitor_offers(offers, {"D"}, 3)

    assert [offer.seller for offer in filtered] == ["A"]
    assert stats == {"delivery": 1, "excluded_sellers": 1, "condition": 1}


# --- Testy save_report_item z nowymi polami i deduplikacja ---

def test_save_report_item_with_super_seller(app):
    """Sprawdza czy save_report_item poprawnie zapisuje nowe pola."""
    from magazyn.db import get_session
    from magazyn.models import PriceReport, PriceReportItem
    from magazyn.price_report_scheduler import save_report_item

    with app.app_context():
        with get_session() as session:
            report = PriceReport(status="pending", items_total=10, items_checked=0)
            session.add(report)
            session.flush()
            report_id = report.id

        result_data = {
            "offer_id": "123",
            "title": "Test",
            "our_price": 100.0,
            "product_size_id": 1,
            "success": True,
            "error": None,
            "my_position": 2,
            "competitors_count": 5,
            "competitors_all_count": 8,
            "cheapest": {
                "price": 95.0,
                "price_with_delivery": 103.99,
                "seller": "KonkurentX",
                "url": "https://allegro.pl/oferta/x-999",
                "is_super_seller": True,
            },
        }
        save_report_item(report_id, result_data)

        with get_session() as session:
            item = session.query(PriceReportItem).filter_by(report_id=report_id, offer_id="123").one()
            report = session.query(PriceReport).filter_by(id=report_id).one()

        assert item.competitor_is_super_seller is True
        assert item.competitors_all_count == 8
        assert item.is_cheapest is False
        assert item.total_offers == 6
        assert report.items_checked == 1


def test_save_report_item_updates_existing_row_without_duplicate(app):
    from magazyn.db import get_session
    from magazyn.models import PriceReport, PriceReportItem
    from magazyn.price_report_scheduler import save_report_item

    with app.app_context():
        with get_session() as session:
            report = PriceReport(status="pending", items_total=10, items_checked=0)
            session.add(report)
            session.flush()
            report_id = report.id

        save_report_item(report_id, {
            "offer_id": "456",
            "title": "Pierwszy zapis",
            "our_price": 200.0,
            "product_size_id": 2,
            "success": True,
            "error": None,
            "my_position": 1,
            "competitors_count": 0,
            "competitors_all_count": 0,
            "cheapest": None,
        })

        save_report_item(report_id, {
            "offer_id": "456",
            "title": "Drugi zapis",
            "our_price": 200.0,
            "product_size_id": 2,
            "success": True,
            "error": None,
            "my_position": 2,
            "competitors_count": 2,
            "competitors_all_count": 4,
            "cheapest": {
                "price": 189.0,
                "price_with_delivery": 189.0,
                "seller": "NowyKonkurent",
                "url": "https://allegro.pl/oferta/x-123",
                "is_super_seller": False,
            },
        })

        with get_session() as session:
            items = session.query(PriceReportItem).filter_by(report_id=report_id, offer_id="456").all()
            report = session.query(PriceReport).filter_by(id=report_id).one()

        assert len(items) == 1
        assert items[0].product_name == "Drugi zapis"
        assert items[0].competitor_seller == "NowyKonkurent"
        assert items[0].our_position == 2
        assert report.items_checked == 1


# --- Test check_single_offer uzywa ceny z API ---

def test_check_single_offer_uses_api_price():
    """Sprawdza ze check_single_offer uzywa ceny z API/bazy (nie z dialogu).
    
    Dialog moze zawierac inna nasza oferte tego samego produktu z inna cena.
    Dlatego uzywamy ceny z bazy (API) a nie z dialogu.
    """
    import asyncio
    from magazyn.scripts.price_checker_ws import PriceCheckResult, CompetitorOffer

    mock_result = PriceCheckResult(
        offer_id="123",
        success=True,
        my_price=110.0,  # Cena z API (parametr)
        competitors=[
            CompetitorOffer(seller="A", price=100.0, price_with_delivery=108.99)
        ],
        cheapest_competitor=CompetitorOffer(
            seller="A", price=100.0, price_with_delivery=108.99
        ),
        my_position=1,
        competitors_all_count=3,
    )

    async def _run():
        with patch("magazyn.scripts.price_checker_ws.check_offer_price", return_value=mock_result):
            from magazyn.price_report_scheduler import check_single_offer

            offer = {
                "offer_id": "123",
                "title": "Test produkt",
                "price": 110.0,  # Cena z bazy/API
                "product_size_id": 1,
            }

            result = await check_single_offer(offer, "192.168.31.147", 9223)

            # Powinien uzyc ceny z API/bazy (110.0)
            assert result["our_price"] == 110.0
            assert result["competitors_all_count"] == 3
            assert result["cheapest"]["is_super_seller"] is False

    asyncio.run(_run())


# --- Test modelu PriceReportItem nowe pola ---

def test_price_report_item_new_columns():
    """Sprawdza ze model PriceReportItem ma nowe kolumny."""
    from magazyn.models import PriceReportItem

    # Sprawdz ze kolumny istnieja w mapperze
    mapper = PriceReportItem.__table__
    col_names = {c.name for c in mapper.columns}
    assert "competitor_is_super_seller" in col_names
    assert "competitors_all_count" in col_names


# --- Test ze item.product_name jest uzywany (nie item.name) ---

def test_change_price_uses_product_name():
    """Weryfikacja ze change_price uzywa product_name a nie name."""
    import inspect
    from magazyn.price_reports import change_price
    source = inspect.getsource(change_price)
    assert "item.product_name" in source
    assert "item.name" not in source
