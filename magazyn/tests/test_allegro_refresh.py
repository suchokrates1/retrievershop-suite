import os
from decimal import Decimal

import pytest
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


def test_refresh_reports_counts_when_no_matches(client, login, monkeypatch):
    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")

    def fake_fetch_offers(token, page):
        assert token == "token"
        assert page == 1
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

    def failing_fetch(token, page):
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

    def failing_fetch(token, page):
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

    def failing_fetch(token, page):
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

    def empty_fetch(token, page):
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

