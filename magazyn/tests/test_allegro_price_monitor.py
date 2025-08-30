import pytest
from decimal import Decimal

from magazyn.allegro_price_monitor import check_prices
from magazyn.db import get_session
from magazyn.models import Product, ProductSize, AllegroOffer


def test_check_prices_grouped(monkeypatch, app_mod):
    calls = {}

    def fake_fetch(barcode):
        calls[barcode] = calls.get(barcode, 0) + 1
        if barcode == "123":
            return [
                {"seller": {"id": "comp"}, "sellingMode": {"price": {"amount": "40"}}}
            ]
        return [
            {"seller": {"id": "comp"}, "sellingMode": {"price": {"amount": "80"}}}
        ]

    messages = []

    monkeypatch.setattr(
        "magazyn.allegro_price_monitor.fetch_product_listing", fake_fetch
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

    check_prices()

    assert calls == {"123": 1, "456": 1}
    assert len(messages) == 2
    assert any("oferta o1" in m for m in messages)
    assert any("oferta o2" in m for m in messages)
    assert all("oferta o3" not in m for m in messages)
