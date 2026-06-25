"""Testy dla poprawek systemu scrapingu i raportow cenowych."""

import asyncio
import json
import logging
from unittest.mock import patch
from datetime import date

import pytest


class _FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 4, 20)


class _FakeWebSocket:
    def __init__(self, *messages):
        self.messages = list(messages)
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        if not self.messages:
            await asyncio.sleep(1)
            return "{}"
        message = self.messages.pop(0)
        return json.dumps(message)


# --- Testy parse_delivery_days ---

def test_parse_delivery_days_jutro():
    with patch("magazyn.services.allegro_price_scraper.delivery.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days("dostawa jutro") == 1


def test_parse_delivery_days_pojutrze():
    with patch("magazyn.services.allegro_price_scraper.delivery.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days("dostawa pojutrze") == 2


def test_parse_delivery_days_za_dni():
    with patch("magazyn.services.allegro_price_scraper.delivery.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days("dostawa za 2-3 dni") == 2


def test_parse_delivery_days_od_chinczyk():
    with patch("magazyn.services.allegro_price_scraper.delivery.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        result = parse_delivery_days("dostawa od 14 dni")
        assert result == 99  # Wysoka wartosc = odfiltruj


def test_parse_delivery_days_none():
    with patch("magazyn.services.allegro_price_scraper.delivery.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days(None) is None
        assert parse_delivery_days("") is None


def test_parse_delivery_days_dzisiaj():
    with patch("magazyn.services.allegro_price_scraper.delivery.date", _FixedDate):
        from magazyn.scripts.price_checker_ws import parse_delivery_days
        assert parse_delivery_days("dostawa dzisiaj") == 0


def test_price_checker_ws_keeps_legacy_exports():
    from magazyn.scripts import price_checker_ws

    assert price_checker_ws.check_offer_price is not None
    assert price_checker_ws.cdp_call is not None
    assert price_checker_ws.CompetitorOffer.__name__ == "CompetitorOffer"
    assert price_checker_ws.PriceCheckResult.__name__ == "PriceCheckResult"


def test_parse_price_handles_thousands_and_nbsp():
    from magazyn.scripts.price_checker_ws import parse_price

    assert parse_price("1 299,00") == 1299.0
    assert parse_price("1\u00a0299,00 zł") == 1299.0
    assert parse_price("1299.50") == 1299.5


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

    offers = parse_competitor_articles(
        [
        {
            "index": 0,
            "offerId": "99988877766",
            "offerUrl": "https://allegro.pl/oferta/x-99988877766",
            "ariaPrice": "119,99",
            "text": "Powystawowy\nod\nSuper Sprzedawcy\nWhatsUpDog\n119,99 zł\n119,99 zł z dostawą\nSmart!\ndostawa jutro",
        }
    ],
        competitor_prices_are_net=False,
    )

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


def test_filter_competitor_offers_excludes_sellers_case_insensitive():
    from magazyn.scripts.price_checker_ws import CompetitorOffer, filter_competitor_offers

    filtered, stats = filter_competitor_offers(
        [CompetitorOffer(seller="PetSet_PL", price=100.0, price_with_delivery=100.0)],
        {" petset_pl "},
        3,
    )

    assert filtered == []
    assert stats == {"delivery": 0, "excluded_sellers": 1, "condition": 0}


def test_is_net_price_article_detects_aria_and_text():
    from magazyn.services.allegro_price_scraper.parser import (
        gross_from_net,
        is_net_price_article,
        parse_competitor_articles,
    )

    assert is_net_price_article("", "aktualna cena netto 187,80 zł")
    assert is_net_price_article("187,80 zł\nnetto", None)
    assert not is_net_price_article("187,80 zł\nbrutto", None)
    assert not is_net_price_article("187,80 zł", "aktualna cena 187,80 zł")

    offers = parse_competitor_articles([
        {
            "index": 0,
            "offerId": "111",
            "ariaPrice": "187,80",
            "ariaPriceLabel": "aktualna cena netto 187,80 zł",
            "text": "od\nSellerX\n187,80 zł\n187,80 zł z dostawą\ndostawa jutro",
        }
    ])
    assert len(offers) == 1
    assert offers[0].price == gross_from_net(187.80)
    assert offers[0].price == 230.99


def test_parse_competitor_articles_converts_when_dialog_shows_net_prices():
    from magazyn.services.allegro_price_scraper.parser import gross_from_net, parse_competitor_articles

    offers = parse_competitor_articles(
        [{
            "index": 0,
            "offerId": "222",
            "ariaPrice": "169,11",
            "ariaPriceLabel": "aktualna cena 169,11 zł",
            "text": "od\nSellerY\n169,11 zł\n169,11 zł z dostawą\ndostawa jutro",
        }],
        dialog_shows_net_prices=True,
        competitor_prices_are_net=False,
    )
    assert len(offers) == 1
    assert offers[0].price == gross_from_net(169.11)


def test_parse_competitor_articles_converts_on_business_session_flag():
    from magazyn.services.allegro_price_scraper.parser import gross_from_net, parse_competitor_articles

    offers = parse_competitor_articles(
        [{
            "index": 0,
            "offerId": "333",
            "ariaPrice": "187,80",
            "ariaPriceLabel": "aktualna cena 187,80 zł",
            "text": "od\niamron\n187,80 zł\n187,80 zł z dostawą\ndostawa jutro",
        }],
        competitor_prices_are_net=True,
    )
    assert len(offers) == 1
    assert offers[0].price == gross_from_net(187.80)
    assert offers[0].price == 230.99


def test_parse_competitor_articles_uses_explicit_vat_gross():
    """Gdy kafelek podaje jawne brutto 'z 23% VAT', uzywamy go zamiast x1.23."""
    from magazyn.services.allegro_price_scraper.parser import parse_competitor_articles

    offers = parse_competitor_articles(
        [{
            "index": 0,
            "offerId": "444",
            "ariaPrice": "187,80",
            "ariaPriceLabel": "187,80 zł aktualna cena",
            "text": (
                "od\npetset_pl\nStan Nowy\n187,80 zł\nnetto\n"
                "dostawa za 0 zł\n231,00 zł z 23% VAT\n"
                "241,49 zł z dostawą z VAT\ndostawa w sobotę"
            ),
        }],
        competitor_prices_are_net=True,
    )
    assert len(offers) == 1
    # 187,80 x 1.23 = 230.99, ale Allegro podaje 231,00 -> bierzemy jawne brutto
    assert offers[0].price == 231.00
    assert offers[0].price_with_delivery == 241.49


def test_parse_competitor_articles_handles_bez_vat_seller():
    """Sprzedawca 'bez VAT' (zwolniony): brutto == netto, BEZ doliczania 23%."""
    from magazyn.services.allegro_price_scraper.parser import parse_competitor_articles

    offers = parse_competitor_articles(
        [{
            "index": 0,
            "offerId": "555",
            "ariaPrice": "219,99",
            "ariaPriceLabel": "219,99 zł aktualna cena",
            "text": (
                "od\nShip_Store1\nStan Nowy\n219,99 zł\nnetto\n"
                "219,99 zł bez VAT\ndarmowa dostawa\ndostawa jutro"
            ),
        }],
        competitor_prices_are_net=True,
    )
    assert len(offers) == 1
    assert offers[0].price == 219.99  # nie 270,59


def test_resolve_gross_prices_sources():
    from magazyn.services.allegro_price_scraper.parser import gross_from_net, resolve_gross_prices

    gross, total, source = resolve_gross_prices("187,80 zł\nnetto\n231,00 zł z 23% VAT", 187.80, 187.80, True)
    assert (gross, source) == (231.00, "vat_line")

    gross, total, source = resolve_gross_prices("219,99 zł bez VAT", 219.99, 219.99, True)
    assert (gross, source) == (219.99, "bez_vat")

    gross, total, source = resolve_gross_prices("169,11 zł netto", 169.11, 169.11, True)
    assert (gross, source) == (gross_from_net(169.11), "assumed_net")

    gross, total, source = resolve_gross_prices("119,99 zł", 119.99, 119.99, False)
    assert (gross, source) == (119.99, "as_is")


def test_http_ssr_fallback_builds_result_from_snapshot():
    from magazyn.services.allegro_price_scraper import checker, http_offers, session
    from magazyn.services.allegro_price_scraper.http_offers import (
        SsrCompetitorSummary,
        SsrOffersSnapshot,
    )

    snapshot = SsrOffersSnapshot(
        offer_id="18675226204",
        product_id=None,
        product_name="Szelki",
        offer_count=7,
        summaries=[
            SsrCompetitorSummary("NAJTANIEJ", 219.99, 219.99, "netto", "", "cheapest"),
            SsrCompetitorSummary("NAJSZYBCIEJ", 187.80, 231.00, "netto", "", "fastest"),
        ],
        source_url="https://business.allegro.pl/oferta/x-18675226204",
    )

    with patch.object(session, "fetch_allegro_session", return_value=object()), \
         patch.object(http_offers, "fetch_offer_ssr_snapshot", return_value=snapshot):
        result = checker._http_ssr_fallback("18675226204", my_price=229.0, cdp_host="h", cdp_port=1)

    assert result is not None
    assert result.success is True
    assert result.source == "ssr"
    assert result.competitors_all_count == 7
    assert result.cheapest_competitor.price == 219.99  # min(219.99, 231.00)
    assert result.my_position == 2  # 229 > 219.99


def test_http_ssr_fallback_disabled_by_flag():
    from magazyn.services.allegro_price_scraper import checker

    with patch.object(checker, "PRICE_CHECK_HTTP_FALLBACK", False):
        assert checker._maybe_http_fallback("1", 100.0, "h", 1) is None


def test_cdp_call_ignores_events_and_returns_matching_response():
    from magazyn.scripts.price_checker_ws import cdp_call

    async def _run():
        websocket = _FakeWebSocket(
            {"method": "Page.loadEventFired"},
            {"id": 7, "result": {"ok": True}},
        )
        result = await cdp_call(websocket, "Runtime.evaluate", msg_id=7, timeout=1)
        assert result["result"] == {"ok": True}
        assert json.loads(websocket.sent[0])["method"] == "Runtime.evaluate"

    asyncio.run(_run())


def test_cdp_call_raises_protocol_error():
    from magazyn.scripts.price_checker_ws import cdp_call

    async def _run():
        websocket = _FakeWebSocket({"id": 5, "error": {"message": "boom"}})
        with pytest.raises(RuntimeError, match="boom"):
            await cdp_call(websocket, "Runtime.evaluate", msg_id=5, timeout=1)

    asyncio.run(_run())


def test_cdp_call_times_out_without_matching_response():
    from magazyn.scripts.price_checker_ws import cdp_call

    async def _run():
        websocket = _FakeWebSocket()
        with pytest.raises(TimeoutError, match="Runtime.evaluate"):
            await cdp_call(websocket, "Runtime.evaluate", msg_id=9, timeout=0.01)

    asyncio.run(_run())


def test_fetch_competitor_offer_payload_uses_custom_msg_id():
    from magazyn.scripts.price_checker_ws import fetch_competitor_offer_payload

    async def _run():
        websocket = _FakeWebSocket({
            "id": 321,
            "result": {"result": {"value": {"articleCount": 0, "articles": [], "containerSource": None}}},
        })
        payload = await fetch_competitor_offer_payload(websocket, msg_id=321)

        assert payload["articleCount"] == 0
        assert json.loads(websocket.sent[0])["id"] == 321

    asyncio.run(_run())


# --- Testy save_report_item z nowymi polami i deduplikacja ---

def test_save_report_item_with_super_seller(app):
    """Sprawdza czy save_report_item poprawnie zapisuje nowe pola."""
    from magazyn.db import get_session
    from magazyn.models.price_reports import PriceReport, PriceReportItem
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
    from magazyn.models.price_reports import PriceReport, PriceReportItem
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


def test_price_report_worker_error_payload_keeps_offer_price():
    from magazyn.services.price_report_worker import _check_offer

    async def failing_check_single_offer(offer, cdp_host, cdp_port):
        raise RuntimeError("CDP padl")

    saved = []

    def save_report_item(report_id, result):
        saved.append((report_id, result))

    _check_offer(
        12,
        {
            "offer_id": "ERR-1",
            "title": "Oferta z błędem",
            "price": 123.45,
            "product_size_id": 9,
        },
        logging.getLogger("test-price-worker"),
        failing_check_single_offer,
        save_report_item,
        "127.0.0.1",
        9223,
    )

    assert saved[0][0] == 12
    assert saved[0][1]["offer_id"] == "ERR-1"
    assert saved[0][1]["our_price"] == 123.45
    assert saved[0][1]["competitors_all_count"] == 0
    assert saved[0][1]["our_siblings"] == []


# --- Test modelu PriceReportItem nowe pola ---

def test_price_report_item_new_columns():
    """Sprawdza ze model PriceReportItem ma nowe kolumny."""
    from magazyn.models.price_reports import PriceReportItem

    # Sprawdz ze kolumny istnieja w mapperze
    mapper = PriceReportItem.__table__
    col_names = {c.name for c in mapper.columns}
    assert "competitor_is_super_seller" in col_names
    assert "competitors_all_count" in col_names


# --- Test ze item.product_name jest uzywany (nie item.name) ---

def test_change_price_uses_product_name():
    """Weryfikacja ze change_price uzywa product_name a nie name."""
    import inspect
    from magazyn.services.price_report_mutation import change_report_item_price
    source = inspect.getsource(change_report_item_price)
    assert "item.product_name" in source
    assert "item.name" not in source
