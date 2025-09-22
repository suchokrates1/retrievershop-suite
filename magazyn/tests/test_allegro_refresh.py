from decimal import Decimal
import os
from types import SimpleNamespace
import json
import threading
import time

import pytest
from requests.exceptions import HTTPError

import magazyn.allegro_sync as sync_mod
import magazyn.config as cfg

from magazyn.db import get_session
from magazyn.models import AllegroOffer, AllegroPriceHistory, Product, ProductSize
from magazyn.allegro_token_refresher import AllegroTokenRefresher
from magazyn.env_tokens import update_allegro_tokens
from magazyn.allegro_api import AUTH_URL, refresh_token as api_refresh_token
from magazyn.metrics import (
    ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL,
    ALLEGRO_TOKEN_REFRESH_RETRIES_TOTAL,
)
from magazyn.settings_store import SettingsPersistenceError, SettingsStore, settings_store


def _set_tokens(access: str | None = None, refresh: str | None = None) -> None:
    settings_store.update(
        {
            "ALLEGRO_ACCESS_TOKEN": None,
            "ALLEGRO_REFRESH_TOKEN": None,
            "ALLEGRO_TOKEN_EXPIRES_IN": None,
            "ALLEGRO_TOKEN_METADATA": None,
        }
    )
    updates = {}
    if access is not None:
        updates["ALLEGRO_ACCESS_TOKEN"] = access
    if refresh is not None:
        updates["ALLEGRO_REFRESH_TOKEN"] = refresh
    if updates:
        settings_store.update(updates)
    else:
        settings_store.update(
            {
                "ALLEGRO_TOKEN_EXPIRES_IN": None,
                "ALLEGRO_TOKEN_METADATA": None,
            }
        )


def test_allegro_oauth_callback_persists_tokens(client, login, monkeypatch):
    _set_tokens()

    original_values = {
        key: settings_store.get(key)
        for key in (
            "ALLEGRO_CLIENT_ID",
            "ALLEGRO_CLIENT_SECRET",
            "ALLEGRO_REDIRECT_URI",
        )
    }
    settings_store.update(
        {
            "ALLEGRO_CLIENT_ID": "client-123",
            "ALLEGRO_CLIENT_SECRET": "secret-456",
            "ALLEGRO_REDIRECT_URI": "https://example.com/callback",
        }
    )

    def fake_get_access_token(client_id, client_secret, code, redirect_uri=None):
        assert client_id == "client-123"
        assert client_secret == "secret-456"
        assert code == "auth-code"
        assert redirect_uri == "https://example.com/callback"
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": "sale:offers",
            "token_type": "bearer",
        }

    monkeypatch.setattr(
        "magazyn.allegro_api.get_access_token", fake_get_access_token
    )

    state = "state-token"
    with client.session_transaction() as session:
        session["allegro_oauth_state"] = state

    try:
        response = client.get(
            "/allegro/oauth/callback",
            query_string={"state": state, "code": "auth-code"},
        )
    finally:
        cleanup = {}
        for key, value in original_values.items():
            cleanup[key] = value if value is not None else None
        settings_store.update(cleanup)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings")

    with client.session_transaction() as session:
        flashes = session.get("_flashes") or []
        assert "allegro_oauth_state" not in session

    assert any("Autoryzacja Allegro zakończona sukcesem." in message for _, message in flashes)

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") == "new-access"
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") == "new-refresh"
    assert settings_store.get("ALLEGRO_TOKEN_EXPIRES_IN") == "3600"

    metadata_raw = settings_store.get("ALLEGRO_TOKEN_METADATA")
    assert metadata_raw is not None
    metadata = json.loads(metadata_raw)
    assert metadata["expires_in"] == 3600
    assert metadata["scope"] == "sale:offers"
    assert metadata["token_type"] == "bearer"
    assert "obtained_at" in metadata
    assert "expires_at" in metadata

    _set_tokens()


def test_allegro_oauth_callback_handles_allegro_error(client, login, monkeypatch):
    _set_tokens()

    original_values = {
        key: settings_store.get(key)
        for key in (
            "ALLEGRO_CLIENT_ID",
            "ALLEGRO_CLIENT_SECRET",
            "ALLEGRO_REDIRECT_URI",
        )
    }
    settings_store.update(
        {
            "ALLEGRO_CLIENT_ID": "client-123",
            "ALLEGRO_CLIENT_SECRET": "secret-456",
            "ALLEGRO_REDIRECT_URI": "https://example.com/callback",
        }
    )

    class DummyResponse:
        status_code = 400

    def failing_get_access_token(*_, **__):
        raise HTTPError(response=DummyResponse())

    monkeypatch.setattr(
        "magazyn.allegro_api.get_access_token", failing_get_access_token
    )

    state = "state-token"
    with client.session_transaction() as session:
        session["allegro_oauth_state"] = state

    try:
        response = client.get(
            "/allegro/oauth/callback",
            query_string={"state": state, "code": "auth-code"},
        )
    finally:
        cleanup = {}
        for key, value in original_values.items():
            cleanup[key] = value if value is not None else None
        settings_store.update(cleanup)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings")

    with client.session_transaction() as session:
        flashes = session.get("_flashes") or []
        assert "allegro_oauth_state" not in session

    assert any("HTTP status 400" in message for _, message in flashes)

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") is None
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") is None
    assert settings_store.get("ALLEGRO_TOKEN_EXPIRES_IN") is None
    assert settings_store.get("ALLEGRO_TOKEN_METADATA") is None

    _set_tokens()

def test_refresh_fetches_and_saves_offers(client, login, monkeypatch):
    _set_tokens("token")

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


def test_sync_offers_records_price_history(monkeypatch, app_mod):
    _set_tokens("token")

    def fake_fetch_offers(token, offset=0, limit=100):
        return {
            "items": {
                "offers": [
                    {
                        "id": "PH1",
                        "name": "History product czerwony M",
                        "sellingMode": {"price": {"amount": "11.00"}},
                    }
                ]
            },
            "links": {},
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        product = Product(name="History product", color="Czerwony")
        size = ProductSize(product=product, size="M")
        session.add_all([product, size])
        session.flush()
        product_size_id = size.id

    result = sync_mod.sync_offers()

    assert result["fetched"] == 1
    assert result["matched"] == 1
    assert any(item["offer_id"] == "PH1" for item in result["trend_report"])

    with get_session() as session:
        history = (
            session.query(AllegroPriceHistory)
            .filter(AllegroPriceHistory.offer_id == "PH1")
            .all()
        )
        assert len(history) == 1
        entry = history[0]
        assert entry.product_size_id == product_size_id
        assert entry.price == Decimal("11.00")


def test_sync_offers_aggregates_paginated_responses(monkeypatch, app_mod):
    _set_tokens("token")

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

    assert result["fetched"] == 3
    assert result["matched"] == 3
    assert isinstance(result["trend_report"], list)
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
    _set_tokens("token")

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

    assert result["fetched"] == 1
    assert result["matched"] == 1
    assert isinstance(result["trend_report"], list)

    with get_session() as session:
        offer = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id == "MC1")
            .one()
        )
        assert offer.product_id == product_id
        assert offer.product_size_id == product_size_id


def test_sync_offers_matches_keyword_models(monkeypatch, app_mod):
    _set_tokens("token")

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        assert offset == 0
        assert limit == 100
        return {
            "items": {
                "offers": [
                    {
                        "id": "KW1",
                        "name": "Mega okazja! Truelove Lumen dla psa czerwone M",
                        "sellingMode": {"price": {"amount": "20.00"}},
                    }
                ]
            },
            "links": {},
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        product = Product(name="Szelki dla psa Truelove Lumen", color="Czerwony")
        size = ProductSize(product=product, size="M")
        session.add_all([product, size])
        session.flush()
        product_id = product.id
        product_size_id = size.id

    result = sync_mod.sync_offers()

    assert result["fetched"] == 1
    assert result["matched"] == 1
    assert isinstance(result["trend_report"], list)

    with get_session() as session:
        offer = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id == "KW1")
            .one()
        )
        assert offer.product_id == product_id
        assert offer.product_size_id == product_size_id


def test_sync_offers_preserves_manual_link_when_no_match(monkeypatch, app_mod):
    _set_tokens("token")

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

    assert result["fetched"] == 1
    assert result["matched"] == 0
    assert isinstance(result["trend_report"], list)

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
    _set_tokens("token")

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

    assert result["fetched"] == 2
    assert result["matched"] == 2
    assert isinstance(result["trend_report"], list)

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
    _set_tokens("token")

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

    assert result["fetched"] == 4
    assert result["matched"] == 4
    assert isinstance(result["trend_report"], list)

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


def test_sync_offers_distinguishes_front_line_variants(monkeypatch, app_mod):
    _set_tokens("token")

    offers = [
        {
            "id": "FL1",
            "name": "Mega okazja! Szelki dla psa Truelove Front Line czerwone M",
            "sellingMode": {"price": {"amount": "30.00"}},
        },
        {
            "id": "FL2",
            "name": "Szelki dla psa Truelove Front Line Premium czerwone M",
            "sellingMode": {"price": {"amount": "35.00"}},
        },
    ]

    def fake_fetch_offers(token, offset=0, limit=100):
        assert token == "token"
        assert offset == 0
        assert limit == 100
        return {"items": {"offers": offers}, "links": {}}

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)

    with get_session() as session:
        front_line = Product(name="Szelki dla psa Truelove Front Line", color="Czerwony")
        front_line_size = ProductSize(product=front_line, size="M")
        premium = Product(
            name="Szelki dla psa Truelove Front Line Premium", color="Czerwony"
        )
        premium_size = ProductSize(product=premium, size="M")
        session.add_all([front_line, front_line_size, premium, premium_size])
        session.flush()
        expectations = {
            "FL1": (front_line.id, front_line_size.id),
            "FL2": (premium.id, premium_size.id),
        }

    result = sync_mod.sync_offers()

    assert result["fetched"] == 2
    assert result["matched"] == 2
    assert isinstance(result["trend_report"], list)

    with get_session() as session:
        stored_offers = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id.in_(expectations))
            .order_by(AllegroOffer.offer_id)
            .all()
        )

    assert len(stored_offers) == 2
    for offer in stored_offers:
        product_id, product_size_id = expectations[offer.offer_id]
        assert offer.product_id == product_id
        assert offer.product_size_id == product_size_id


def test_refresh_on_unauthorized_fetch(client, login, monkeypatch):
    _set_tokens("expired-token", "refresh-token")

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
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)
    monkeypatch.setattr(sync_mod.allegro_api, "refresh_token", fake_refresh)
    persisted = []

    original_update = sync_mod.update_allegro_tokens

    def capture_tokens(
        access_token=None, refresh_token=None, expires_in=None, metadata=None
    ):
        persisted.append(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": expires_in,
            }
        )
        original_update(access_token, refresh_token, expires_in, metadata)

    monkeypatch.setattr("magazyn.allegro_sync.update_allegro_tokens", capture_tokens)

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
    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") == "new-access"
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") == "new-refresh"
    assert persisted == [
        {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
    ]

    with get_session() as session:
        offers = session.query(AllegroOffer).all()
        assert len(offers) == 1
        offer = offers[0]
        assert offer.offer_id == "O2"
        assert offer.title == "Prod2 zielony M"
        assert offer.price == Decimal("20.00")
        assert offer.product_id == product_id


def test_refresh_reports_counts_when_no_matches(client, login, monkeypatch):
    _set_tokens("token")

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
    _set_tokens("token")

    def failing_fetch(token, offset=0, limit=100):
        class DummyResponse:
            status_code = 403

        raise HTTPError(response=DummyResponse())

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", failing_fetch)

    with pytest.raises(RuntimeError) as excinfo:
        sync_mod.sync_offers()

    assert "HTTP status 403" in str(excinfo.value)


def test_refresh_flashes_error_on_sync_failure(client, login, monkeypatch):
    _set_tokens("token")

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
    _set_tokens(None, "bad-token")

    clear_calls: list[bool] = []

    def fake_clear():
        clear_calls.append(True)
        _set_tokens()

    monkeypatch.setattr(sync_mod, "clear_allegro_tokens", fake_clear)

    def failing_refresh(token):
        class DummyResponse:
            status_code = 401

        raise HTTPError(response=DummyResponse())

    monkeypatch.setattr(sync_mod.allegro_api, "refresh_token", failing_refresh)

    with pytest.raises(RuntimeError) as excinfo:
        sync_mod.sync_offers()

    message = str(excinfo.value)
    assert "please re-authorize" in message
    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") is None
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") is None
    assert clear_calls == [True]


def test_refresh_clears_tokens_when_refresh_during_sync_fails(client, login, monkeypatch):
    _set_tokens("expired-token", "bad-refresh")

    clear_calls: list[bool] = []

    def fake_clear():
        clear_calls.append(True)
        _set_tokens()

    monkeypatch.setattr(sync_mod, "clear_allegro_tokens", fake_clear)

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
    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") is None
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") is None
    assert clear_calls == [True]


def test_refresh_handles_empty_response(client, login, monkeypatch):
    _set_tokens("token")

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


def test_sync_offers_aborts_when_settings_store_is_read_only(
    monkeypatch, app_mod
):
    monkeypatch.delenv("ALLEGRO_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)
    _set_tokens(refresh="refresh-token")

    monkeypatch.setattr(
        sync_mod.allegro_api,
        "refresh_token",
        lambda refresh: {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
        },
    )

    def unexpected_fetch(*args, **kwargs):
        raise AssertionError("fetch_offers should not be called when persistence fails")

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", unexpected_fetch)

    def failing_update(values):
        raise SettingsPersistenceError("read-only")

    monkeypatch.setattr(sync_mod.settings_store, "update", failing_update)

    metric = sync_mod.ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="settings_store")
    initial_value = metric._value.get()

    with pytest.raises(RuntimeError) as excinfo:
        sync_mod.sync_offers()

    assert "settings store is read-only" in str(excinfo.value)
    assert metric._value.get() == initial_value + 1
    assert os.environ.get("ALLEGRO_ACCESS_TOKEN") is None
    assert os.environ.get("ALLEGRO_REFRESH_TOKEN") == "refresh-token"

    os.environ.pop("ALLEGRO_ACCESS_TOKEN", None)
    os.environ.pop("ALLEGRO_REFRESH_TOKEN", None)


def test_sync_offers_uses_tokens_from_external_process(
    app_mod, monkeypatch, allegro_tokens
):
    allegro_tokens("expired-token", "refresh-token")
    settings_store.reload()

    monkeypatch.setenv("DB_PATH", cfg.settings.DB_PATH)
    external_store = SettingsStore()
    assert external_store.get("ALLEGRO_ACCESS_TOKEN") == "expired-token"

    calls = {"fetch": 0}

    def fake_fetch_offers(token, offset=0, limit=100):
        calls["fetch"] += 1
        if calls["fetch"] == 1:
            assert token == "expired-token"
            external_store.update(
                {
                    "ALLEGRO_ACCESS_TOKEN": "fresh-token",
                    "ALLEGRO_REFRESH_TOKEN": "fresh-refresh",
                }
            )
            error = HTTPError("401 Unauthorized")
            error.response = SimpleNamespace(status_code=401)
            raise error
        assert token == "fresh-token"
        return {"items": {"offers": []}, "links": {}}

    def fail_refresh_token(refresh):
        raise AssertionError("refresh_token should not be called")

    monkeypatch.setattr(sync_mod.allegro_api, "fetch_offers", fake_fetch_offers)
    monkeypatch.setattr(sync_mod.allegro_api, "refresh_token", fail_refresh_token)

    result = sync_mod.sync_offers()

    assert result["fetched"] == 0
    assert result["matched"] == 0
    assert isinstance(result["trend_report"], list)
    assert calls["fetch"] == 2


def test_token_refresher_refreshes_tokens_automatically(monkeypatch):
    _set_tokens("initial-token", "refresh-token")
    update_allegro_tokens("initial-token", "refresh-token", 1)

    refresh_called = threading.Event()

    def fake_refresh(token):
        assert token == "refresh-token"
        refresh_called.set()
        return {
            "access_token": "refreshed-access",
            "refresh_token": "refreshed-refresh",
            "expires_in": 1800,
            "scope": "sale:orders",
        }

    monkeypatch.setattr("magazyn.allegro_api.refresh_token", fake_refresh)

    success_metric = ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="success")
    success_start = success_metric._value.get()

    refresher = AllegroTokenRefresher(
        margin_seconds=5,
        idle_interval_seconds=0.05,
        error_backoff_initial=0.05,
        error_backoff_max=0.1,
    )

    try:
        refresher.start()
        assert refresh_called.wait(2.0)
    finally:
        refresher.stop()

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") == "refreshed-access"
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") == "refreshed-refresh"

    metadata_raw = settings_store.get("ALLEGRO_TOKEN_METADATA")
    assert metadata_raw is not None
    metadata = json.loads(metadata_raw)
    assert metadata["expires_in"] == 1800
    assert metadata["scope"] == "sale:orders"
    assert "expires_at" in metadata
    assert "obtained_at" in metadata

    success_end = success_metric._value.get()
    assert success_end == success_start + 1

    _set_tokens()


def test_token_refresher_retries_after_failure(monkeypatch):
    _set_tokens("initial-token", "refresh-token")
    update_allegro_tokens("initial-token", "refresh-token", 1)

    call_times: list[float] = []
    refresh_complete = threading.Event()

    class DummyResponse:
        status_code = 500

    def flaky_refresh(token):
        assert token == "refresh-token"
        call_times.append(time.monotonic())
        if len(call_times) == 1:
            raise HTTPError(response=DummyResponse())
        refresh_complete.set()
        return {
            "access_token": "final-access",
            "refresh_token": "refresh-token",
            "expires_in": 900,
        }

    monkeypatch.setattr("magazyn.allegro_api.refresh_token", flaky_refresh)

    error_metric = ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="error")
    success_metric = ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="success")
    retries_metric = ALLEGRO_TOKEN_REFRESH_RETRIES_TOTAL
    error_start = error_metric._value.get()
    success_start = success_metric._value.get()
    retries_start = retries_metric._value.get()

    refresher = AllegroTokenRefresher(
        margin_seconds=5,
        idle_interval_seconds=0.05,
        error_backoff_initial=0.2,
        error_backoff_max=0.2,
    )

    try:
        refresher.start()
        assert refresh_complete.wait(3.0)
    finally:
        refresher.stop()

    assert len(call_times) >= 2
    assert call_times[1] - call_times[0] >= 0.18

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") == "final-access"
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") == "refresh-token"

    assert error_metric._value.get() == error_start + 1
    assert success_metric._value.get() == success_start + 1
    assert retries_metric._value.get() == retries_start + 1

    _set_tokens()

def test_refresh_token_prefers_settings_store(monkeypatch):
    original_values = {}
    for key in ("ALLEGRO_CLIENT_ID", "ALLEGRO_CLIENT_SECRET"):
        try:
            original_values[key] = settings_store.get(key)
        except SettingsPersistenceError:
            original_values[key] = None

    for env_key in ("ALLEGRO_CLIENT_ID", "ALLEGRO_CLIENT_SECRET"):
        monkeypatch.delenv(env_key, raising=False)

    settings_store.update(
        {
            "ALLEGRO_CLIENT_ID": "settings-client-id",
            "ALLEGRO_CLIENT_SECRET": "settings-client-secret",
        }
    )

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "new-token", "refresh_token": "new-refresh"}

    def fake_post(url, data, auth=None, timeout=None):
        assert url == AUTH_URL
        assert auth == ("settings-client-id", "settings-client-secret")
        assert data == {"grant_type": "refresh_token", "refresh_token": "refresh-token"}
        return DummyResponse()

    monkeypatch.setattr("magazyn.allegro_api.requests.post", fake_post)

    try:
        result = api_refresh_token("refresh-token")
    finally:
        cleanup = {}
        for key, value in original_values.items():
            cleanup[key] = value if value is not None else None
        settings_store.update(cleanup)

    assert result == {"access_token": "new-token", "refresh_token": "new-refresh"}

