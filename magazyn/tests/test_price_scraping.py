"""Testy dla poprawek systemu scrapingu i raportow cenowych."""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal


# --- Testy parse_delivery_days ---

def test_parse_delivery_days_jutro():
    from magazyn.scripts.price_checker_ws import parse_delivery_days
    assert parse_delivery_days("dostawa jutro") == 1


def test_parse_delivery_days_pojutrze():
    from magazyn.scripts.price_checker_ws import parse_delivery_days
    assert parse_delivery_days("dostawa pojutrze") == 2


def test_parse_delivery_days_za_dni():
    from magazyn.scripts.price_checker_ws import parse_delivery_days
    assert parse_delivery_days("dostawa za 2-3 dni") == 2


def test_parse_delivery_days_od_chinczyk():
    from magazyn.scripts.price_checker_ws import parse_delivery_days
    result = parse_delivery_days("dostawa od 14 dni")
    assert result == 99  # Wysoka wartosc = odfiltruj


def test_parse_delivery_days_none():
    from magazyn.scripts.price_checker_ws import parse_delivery_days
    assert parse_delivery_days(None) is None
    assert parse_delivery_days("") is None


def test_parse_delivery_days_dzisiaj():
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


# --- Testy save_report_item z nowymi polami ---

def test_save_report_item_with_super_seller():
    """Sprawdza czy save_report_item poprawnie zapisuje nowe pola."""
    from magazyn.price_report_scheduler import save_report_item

    mock_session = MagicMock()
    mock_report = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = mock_report

    with patch("magazyn.db.get_session") as mock_gs:
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

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
        save_report_item(1, result_data)

        # Sprawdz ze item zostal dodany z nowymi polami
        added_item = mock_session.add.call_args[0][0]
        assert added_item.competitor_is_super_seller is True
        assert added_item.competitors_all_count == 8
        assert added_item.is_cheapest is False  # 100 > 95
        assert added_item.total_offers == 6  # 5 competitors + 1


def test_save_report_item_no_competitors():
    """Test zapisu gdy brak konkurencji."""
    from magazyn.price_report_scheduler import save_report_item

    mock_session = MagicMock()
    mock_report = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = mock_report

    with patch("magazyn.db.get_session") as mock_gs:
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        result_data = {
            "offer_id": "456",
            "title": "Brak konkurencji",
            "our_price": 200.0,
            "product_size_id": 2,
            "success": True,
            "error": None,
            "my_position": 1,
            "competitors_count": 0,
            "competitors_all_count": 0,
            "cheapest": None,
        }
        save_report_item(1, result_data)

        added_item = mock_session.add.call_args[0][0]
        assert added_item.is_cheapest is True  # Domyslnie najtansi
        assert added_item.competitor_is_super_seller is None


# --- Test check_single_offer uzywa ceny z dialogu ---

def test_check_single_offer_uses_dialog_price():
    """Sprawdza ze check_single_offer uzywa ceny z dialogu zamiast z bazy."""
    import asyncio
    from magazyn.scripts.price_checker_ws import PriceCheckResult, CompetitorOffer

    mock_result = PriceCheckResult(
        offer_id="123",
        success=True,
        my_price=95.0,  # Cena z dialogu (aktualna)
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
                "price": 110.0,  # Stara cena z bazy
                "product_size_id": 1,
            }

            result = await check_single_offer(offer, "192.168.31.147", 9223)

            # Powinien uzyc ceny z dialogu (95.0) zamiast z bazy (110.0)
            assert result["our_price"] == 95.0
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
