from decimal import Decimal

from magazyn.allegro_price_monitor import COMPETITOR_SUFFIX, check_prices
from magazyn.db import get_session
from magazyn.models import (
    AllegroOffer,
    AllegroPriceHistory,
    Product,
    ProductSize,
)
from magazyn.allegro_scraper import Offer


def test_check_prices_grouped(monkeypatch, app_mod):
    calls = {}

    def fake_fetch(offer_id, *, stop_seller=None, limit=30, headless=True):
        calls[offer_id] = calls.get(offer_id, 0) + 1
        if offer_id == "o1":
            return [Offer("Oferta", "40,00 zł", "Sprzedawca", "https://allegro.pl/oferta/other")], []
        return [Offer("Oferta", "80,00 zł", "Sprzedawca", "https://allegro.pl/oferta/another")], []

    messages = []

    monkeypatch.setattr(
        "magazyn.allegro_price_monitor.fetch_competitors_for_offer",
        fake_fetch,
    )
    monkeypatch.setattr(
        "magazyn.allegro_price_monitor.send_messenger", lambda msg: messages.append(msg)
    )

    with get_session() as session:
        product = Product(name="Prod")
        session.add(product)
        session.flush()
        ps1 = ProductSize(product_id=product.id, size="M", barcode="123")
        ps2 = ProductSize(product_id=product.id, size="L", barcode="456")
        session.add_all([ps1, ps2])
        session.flush()
        session.add_all(
            [
                AllegroOffer(
                    offer_id="o1",
                    title="o1",
                    price=Decimal("50.0"),
                    product_id=product.id,
                    product_size_id=ps1.id,
                ),
                AllegroOffer(
                    offer_id="o2",
                    title="o2",
                    price=Decimal("60.0"),
                    product_id=product.id,
                    product_size_id=ps1.id,
                ),
                AllegroOffer(
                    offer_id="o3",
                    title="o3",
                    price=Decimal("70.0"),
                    product_id=product.id,
                    product_size_id=ps2.id,
                ),
            ]
        )

    result = check_prices()

    assert calls == {"o1": 1, "o3": 1}
    assert len(messages) == 2
    assert any("oferta o1" in m for m in messages)
    assert any("oferta o2" in m for m in messages)
    assert all("oferta o3" not in m for m in messages)
    assert result["alerts"] == 2
    assert isinstance(result["trend_report"], list)

    with get_session() as session:
        history = session.query(AllegroPriceHistory).all()
        recorded_ids = {entry.offer_id for entry in history}
        assert "o1" in recorded_ids
        assert f"o1{COMPETITOR_SUFFIX}" in recorded_ids
        assert any(item["offer_id"] == f"o1{COMPETITOR_SUFFIX}" for item in result["trend_report"])


def test_check_prices_readonly_db(monkeypatch, app_mod, caplog):
    def fake_fetch(offer_id, *, stop_seller=None, limit=30, headless=True):
        return [Offer("Oferta", "40,00 zł", "Sprzedawca", "https://allegro.pl/oferta/other")], []

    messages: list[str] = []

    monkeypatch.setattr(
        "magazyn.allegro_price_monitor.fetch_competitors_for_offer",
        fake_fetch,
    )
    monkeypatch.setattr(
        "magazyn.allegro_price_monitor.send_messenger",
        lambda msg: messages.append(msg),
    )

    with get_session() as session:
        product = Product(name="Readonly")
        session.add(product)
        session.flush()
        size = ProductSize(product_id=product.id, size="M", barcode="123")
        session.add(size)
        session.flush()
        session.add(
            AllegroOffer(
                offer_id="o-readonly",
                title="o-readonly",
                price=Decimal("50.0"),
                product_id=product.id,
                product_size_id=size.id,
            )
        )

    def forbid_record(*args, **kwargs):  # pragma: no cover - sanity check
        raise AssertionError("record_price_point should not be called when DB is read-only")

    monkeypatch.setattr(
        "magazyn.allegro_price_monitor.allegro_prices.record_price_point",
        forbid_record,
    )

    monkeypatch.setattr(
        "magazyn.allegro_price_monitor._is_db_writable",
        lambda path: False,
    )

    caplog.set_level("WARNING", logger="magazyn.allegro_price_monitor")

    result = check_prices()

    assert result["alerts"] == 1
    assert messages and "Niższa cena" in messages[0]
    assert any("read-only" in rec.message.lower() for rec in caplog.records)
