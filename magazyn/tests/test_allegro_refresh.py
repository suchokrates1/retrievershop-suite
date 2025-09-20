import os
from decimal import Decimal

from requests.exceptions import HTTPError

import magazyn.allegro_sync as sync_mod

from magazyn.db import get_session
from magazyn.models import Product, ProductSize, AllegroOffer


def test_refresh_fetches_and_saves_offers(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")

    def fake_fetch_offers(token, page):
        assert token == "token"
        assert page == 1
        return {
            "items": {
                "offers": [
                    {
                        "id": "O1",
                        "name": "Test offer",
                        "ean": "123456",
                        "sellingMode": {"price": {"amount": "15.00"}},
                    }
                ]
            },
            "links": {},
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        product = Product(name="Prod", color="red")
        ps = ProductSize(product=product, size="L", barcode="123456")
        session.add(product)
        session.add(ps)
        session.flush()
        product_id = product.id

    response = client.post("/allegro/refresh")
    assert response.status_code == 302

    with get_session() as session:
        offers = session.query(AllegroOffer).all()
        assert len(offers) == 1
        offer = offers[0]
        assert offer.offer_id == "O1"
        assert offer.title == "Test offer"
        assert offer.price == Decimal("15.00")
        assert offer.product_id == product_id


def test_refresh_on_unauthorized_fetch(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "expired-token")
    monkeypatch.setenv("ALLEGRO_REFRESH_TOKEN", "refresh-token")

    attempts = {"count": 0}

    def fake_fetch_offers(token, page):
        attempts["count"] += 1
        assert page == 1
        if attempts["count"] == 1:
            class DummyResponse:
                status_code = 401

            raise HTTPError(response=DummyResponse())
        assert token == "new-access"
        return {
            "items": {
                "offers": [
                    {
                        "id": "O2",
                        "name": "Refreshed offer",
                        "ean": "654321",
                        "sellingMode": {"price": {"amount": "20.00"}},
                    }
                ]
            },
            "links": {},
        }

    refresh_calls = {"count": 0}

    def fake_refresh(token):
        refresh_calls["count"] += 1
        assert token == "refresh-token"
        return {"access_token": "new-access", "refresh_token": "new-refresh"}

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)
    monkeypatch.setattr(sync_mod.allegro_api, "refresh_token", fake_refresh)

    with get_session() as session:
        product = Product(name="Prod2", color="blue")
        ps = ProductSize(product=product, size="M", barcode="654321")
        session.add(product)
        session.add(ps)
        session.flush()
        product_id = product.id

    response = client.post("/allegro/refresh")
    assert response.status_code == 302

    assert attempts["count"] == 2
    assert refresh_calls["count"] == 1
    assert os.getenv("ALLEGRO_ACCESS_TOKEN") == "new-access"
    assert os.getenv("ALLEGRO_REFRESH_TOKEN") == "new-refresh"

    with get_session() as session:
        offers = session.query(AllegroOffer).all()
        assert len(offers) == 1
        offer = offers[0]
        assert offer.offer_id == "O2"
        assert offer.title == "Refreshed offer"
        assert offer.price == Decimal("20.00")
        assert offer.product_id == product_id

