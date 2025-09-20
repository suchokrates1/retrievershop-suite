import os
from decimal import Decimal

import pytest
from requests.exceptions import HTTPError

import magazyn.allegro_sync as sync_mod

from magazyn.db import get_session
from magazyn.models import Product, ProductSize, AllegroOffer


def test_refresh_fetches_and_saves_offers(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        assert offset == 0
        assert limit == 100
        return {
            "items": {
                "offers": [
                    {
                        "id": "O1",
                        "name": "Test offer czerwony",
                        "ean": "ignored",
                        "sellingMode": {"price": {"amount": "15.00"}},
                    }
                ]
            },
            "links": {},
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        product = Product(name="Test offer", color="Czerwony")
        ps = ProductSize(product=product, size="Uniwersalny")
        session.add(product)
        session.add(ps)
        session.flush()
        product_id = product.id

    response = client.post("/allegro/refresh")
    assert response.status_code == 302

    with client.session_transaction() as session:
        flashes = session.get("_flashes") or []

    assert any(
        "Oferty zaktualizowane" in message
        and "pobrano 1" in message
        and "zaktualizowano 1" in message
        for _, message in flashes
    )

    with get_session() as session:
        offers = session.query(AllegroOffer).all()
        assert len(offers) == 1
        offer = offers[0]
        assert offer.offer_id == "O1"
        assert offer.title == "Test offer czerwony"
        assert offer.price == Decimal("15.00")
        assert offer.product_id == product_id


def test_sync_offers_aggregates_paginated_responses(monkeypatch, app_mod):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    responses = [
        {
            "items": {
                "offers": [
                    {
                        "id": "P1",
                        "name": "Paginated product 1 czerwony L",
                        "ean": "111000",
                        "sellingMode": {"price": {"amount": "12.00"}},
                    },
                    {
                        "id": "P2",
                        "name": "Paginated product 2 zielony L",
                        "ean": "222000",
                        "sellingMode": {"price": {"amount": "13.00"}},
                    },
                ]
            },
            "nextPage": {"offset": 2, "limit": 2},
            "links": {
                "next": {
                    "href": "https://api.allegro.pl/sale/offers?offset=2&limit=2"
                }
            },
        },
        {
            "items": {
                "offers": [
                    {
                        "id": "P3",
                        "name": "Paginated product 3 niebieski L",
                        "ean": "333000",
                        "sellingMode": {"price": {"amount": "14.00"}},
                    }
                ]
            },
            "links": {},
        },
    ]

    calls = []

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        calls.append({"offset": offset, "limit": limit})
        return responses[len(calls) - 1]

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        products = []
        sizes = []
        colors = ["Czerwony", "Zielony", "Niebieski"]
        for idx, color in enumerate(colors, start=1):
            product = Product(name=f"Paginated product {idx}", color=color)
            size = ProductSize(product=product, size="L")
            products.append(product)
            sizes.append(size)
        session.add_all(products + sizes)
        session.flush()

    result = sync_mod.sync_offers()

    assert result == {"fetched": 3, "matched": 3}
    assert len(calls) == 2
    assert calls[0] == {"offset": 0, "limit": 100}
    assert calls[1] == {"offset": 2, "limit": 2}

    with get_session() as session:
        offers = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id.in_(["P1", "P2", "P3"]))
            .order_by(AllegroOffer.offer_id)
            .all()
        )
        assert len(offers) == 3
        assert [offer.title for offer in offers] == [
            "Paginated product 1 czerwony L",
            "Paginated product 2 zielony L",
            "Paginated product 3 niebieski L",
        ]


def test_sync_offers_matches_single_color_component(monkeypatch, app_mod):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        assert offset == 0
        assert limit == 100
        return {
            "items": {
                "offers": [
                    {
                        "id": "MC1",
                        "name": "Dwukolorowy produkt biały M",
                        "sellingMode": {"price": {"amount": "10.00"}},
                    }
                ]
            },
            "links": {},
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        product = Product(name="Dwukolorowy produkt", color="Czerwono-biały")
        size = ProductSize(product=product, size="M")
        session.add_all([product, size])
        session.flush()
        product_id = product.id
        product_size_id = size.id

    result = sync_mod.sync_offers()

    assert result == {"fetched": 1, "matched": 1}

    with get_session() as session:
        offer = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id == "MC1")
            .one()
        )
        assert offer.product_id == product_id
        assert offer.product_size_id == product_size_id


def test_sync_offers_preserves_manual_link_when_no_match(monkeypatch, app_mod):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        assert offset == 0
        assert limit == 100
        return {
            "items": {
                "offers": [
                    {
                        "id": "MAN1",
                        "name": "Niepowiązany produkt niebieski S",
                        "sellingMode": {"price": {"amount": "25.00"}},
                    }
                ]
            },
            "links": {},
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        product = Product(name="Manualny produkt", color="Zielony")
        size = ProductSize(product=product, size="L")
        session.add_all([product, size])
        session.flush()
        product_id = product.id
        product_size_id = size.id

        offer = AllegroOffer(
            offer_id="MAN1",
            title="Ręcznie powiązana oferta",
            price=Decimal("10.00"),
            product_id=product_id,
            product_size_id=product_size_id,
        )
        session.add(offer)
        session.commit()

    result = sync_mod.sync_offers()

    assert result == {"fetched": 1, "matched": 0}

    with get_session() as session:
        refreshed_offer = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id == "MAN1")
            .one()
        )
        assert refreshed_offer.product_id == product_id
        assert refreshed_offer.product_size_id == product_size_id
        assert refreshed_offer.price == Decimal("25.00")


def test_sync_offers_handles_non_mapping_selling_mode(monkeypatch, app_mod):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        assert offset == 0
        assert limit == 100
        return {
            "items": {
                "offers": [
                    {
                        "id": "NM1",
                        "name": "Prod NM1 czarne S",
                        "ean": "111111",
                        "sellingMode": None,
                    },
                    {
                        "id": "NM2",
                        "name": "Prod NM2 różowe M",
                        "ean": "222222",
                        "sellingMode": {"price": "unexpected"},
                    },
                ]
            },
            "links": {},
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        product_one = Product(name="Prod NM1", color="Czarny")
        size_one = ProductSize(product=product_one, size="S")
        product_two = Product(name="Prod NM2", color="Różowy")
        size_two = ProductSize(product=product_two, size="M")
        session.add_all([product_one, size_one, product_two, size_two])
        session.flush()

    result = sync_mod.sync_offers()

    assert result == {"fetched": 2, "matched": 2}

    with get_session() as session:
        offers = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id.in_(["NM1", "NM2"]))
            .order_by(AllegroOffer.offer_id)
            .all()
        )
        assert len(offers) == 2
        for offer in offers:
            assert offer.price == Decimal("0.00")
            assert offer.product_id is not None
            assert offer.product_size_id is not None


def test_sync_offers_matches_alias_variants(monkeypatch, app_mod):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    offers = [
        {
            "id": "AL1",
            "name": "Szelki dla psa Truelove Fron Line Premium M czarne",
            "sellingMode": {"price": {"amount": "25.00"}},
        },
        {
            "id": "AL2",
            "name": "Szelki dla psa Truelove Front Line Premium Tropical L turkusowe",
            "sellingMode": {"price": {"amount": "26.00"}},
        },
        {
            "id": "AL3",
            "name": "Szelki dla psa Truelove FrontLine Lumen S czerwone",
            "sellingMode": {"price": {"amount": "27.00"}},
        },
        {
            "id": "AL4",
            "name": "Szelki dla psa Truelove Front Line Premium Blossom XS różowe",
            "sellingMode": {"price": {"amount": "28.00"}},
        },
    ]

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        assert offset == 0
        assert limit == 100
        return {"items": {"offers": offers}, "links": {}}

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        expectations = {}
        product_specs = [
            ("Szelki dla psa Truelove Front Line Premium", "Czarny", "M"),
            ("Szelki dla psa Truelove Tropical", "Turkusowy", "L"),
            ("Szelki dla psa Truelove Lumen", "Czerwony", "S"),
            ("Szelki dla psa Truelove Blossom", "Różowy", "XS"),
        ]
        for idx, (name, color, size) in enumerate(product_specs, start=1):
            product = Product(name=name, color=color)
            size_obj = ProductSize(product=product, size=size)
            session.add_all([product, size_obj])
            session.flush()
            expectations[f"AL{idx}"] = (product.id, size_obj.id)

    result = sync_mod.sync_offers()

    assert result == {"fetched": 4, "matched": 4}

    with get_session() as session:
        stored_offers = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id.in_(expectations))
            .order_by(AllegroOffer.offer_id)
            .all()
        )

    assert len(stored_offers) == 4
    for offer in stored_offers:
        product_id, product_size_id = expectations[offer.offer_id]
        assert offer.product_id == product_id
        assert offer.product_size_id == product_size_id


def test_refresh_on_unauthorized_fetch(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "expired-token")
    monkeypatch.setenv("ALLEGRO_REFRESH_TOKEN", "refresh-token")

    attempts = {"count": 0}

    def fake_fetch_offers(token, offset=0, limit=100):
        attempts["count"] += 1
        assert offset == 0
        if attempts["count"] == 1:
            class DummyResponse:
                status_code = 401

            raise HTTPError(response=DummyResponse())
        assert token == "new-access"
        assert limit == 100
        return {
            "items": {
                "offers": [
                    {
                        "id": "O2",
                        "name": "Prod2 zielony M",
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
        product = Product(name="Prod2", color="Zielony")
        ps = ProductSize(product=product, size="M")
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
        assert offer.title == "Prod2 zielony M"
        assert offer.price == Decimal("20.00")
        assert offer.product_id == product_id


def test_refresh_reports_counts_when_no_matches(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        assert offset == 0
        assert limit == 100
        return {
            "items": {
                "offers": [
                    {
                        "id": "O3",
                        "name": "Unmatched offer",
                        "ean": "999999",
                        "sellingMode": {"price": {"amount": "10.00"}},
                    }
                ]
            },
            "links": {},
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    response = client.post("/allegro/refresh")
    assert response.status_code == 302

    with client.session_transaction() as session:
        flashes = session.get("_flashes") or []

    assert any(
        "Oferty zaktualizowane" in message
        and "pobrano 1" in message
        and "zaktualizowano 0" in message
        for _, message in flashes
    )

    with get_session() as session:
        offers = session.query(AllegroOffer).all()
        assert len(offers) == 1
        offer = offers[0]
        assert offer.offer_id == "O3"
        assert offer.title == "Unmatched offer"
        assert offer.price == Decimal("10.00")
        assert offer.product_id is None
        assert offer.product_size_id is None

    response = client.get("/allegro/offers")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "Unmatched offer" in body


def test_sync_offers_raises_on_unrecoverable_error(monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    def failing_fetch(token, offset=0, limit=100):
        class DummyResponse:
            status_code = 403

        raise HTTPError(response=DummyResponse())

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", failing_fetch)

    with pytest.raises(RuntimeError) as excinfo:
        sync_mod.sync_offers()

    assert "HTTP status 403" in str(excinfo.value)


def test_refresh_flashes_error_on_sync_failure(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    def failing_fetch(token, offset=0, limit=100):
        class DummyResponse:
            status_code = 403

        raise HTTPError(response=DummyResponse())

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", failing_fetch)

    response = client.post("/allegro/refresh")
    assert response.status_code == 302

    with client.session_transaction() as session:
        flashes = session.get("_flashes") or []

    assert any(
        "Błąd synchronizacji ofert" in message and "HTTP status 403" in message
        for _, message in flashes
    )


def test_sync_offers_clears_tokens_when_initial_refresh_fails(monkeypatch):
    monkeypatch.delenv("ALLEGRO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("ALLEGRO_REFRESH_TOKEN", "bad-token")

    def failing_refresh(token):
        class DummyResponse:
            status_code = 401

        raise HTTPError(response=DummyResponse())

    monkeypatch.setattr(sync_mod.allegro_api, "refresh_token", failing_refresh)

    with pytest.raises(RuntimeError) as excinfo:
        sync_mod.sync_offers()

    message = str(excinfo.value)
    assert "please re-authorize" in message
    assert os.getenv("ALLEGRO_ACCESS_TOKEN") is None
    assert os.getenv("ALLEGRO_REFRESH_TOKEN") is None


def test_refresh_clears_tokens_when_refresh_during_sync_fails(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "expired-token")
    monkeypatch.setenv("ALLEGRO_REFRESH_TOKEN", "bad-refresh")

    def failing_fetch(token, offset=0, limit=100):
        class DummyResponse:
            status_code = 401

        raise HTTPError(response=DummyResponse())

    def failing_refresh(token):
        class DummyResponse:
            status_code = 400

        raise HTTPError(response=DummyResponse())

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", failing_fetch)
    monkeypatch.setattr(sync_mod.allegro_api, "refresh_token", failing_refresh)

    response = client.post("/allegro/refresh")
    assert response.status_code == 302

    with client.session_transaction() as session:
        flashes = session.get("_flashes") or []

    assert any(
        "Błąd synchronizacji ofert" in message and "please re-authorize" in message
        for _, message in flashes
    )
    assert os.getenv("ALLEGRO_ACCESS_TOKEN") is None
    assert os.getenv("ALLEGRO_REFRESH_TOKEN") is None


def test_refresh_handles_empty_response(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    def empty_fetch(token, offset=0, limit=100):
        return None

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", empty_fetch)

    response = client.post("/allegro/refresh")
    assert response.status_code == 302

    with client.session_transaction() as session:
        flashes = session.get("_flashes") or []

    assert any(
        "Błąd synchronizacji ofert" in message
        and "malformed response" in message
        for _, message in flashes
    )
    assert all("'NoneType'" not in message for _, message in flashes)

    with get_session() as session:
        assert session.query(AllegroOffer).count() == 0

