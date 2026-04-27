from decimal import Decimal
import re

import json

import pytest
import requests

import magazyn.allegro_api as allegro_api
from magazyn.settings_store import settings_store

from magazyn.config import settings
from magazyn.db import get_session
from magazyn.models.allegro import AllegroOffer
from magazyn.models.products import Product, ProductSize
from magazyn.allegro_api import fetch_product_listing
import magazyn.allegro as allegro_views


def test_offers_page_shows_manual_mapping_dropdown(client, login):
    with get_session() as session:
        product = Product(name="Szelki spacerowe", color="Czerwone")
        session.add(product)
        session.flush()
        size = ProductSize(
            product_id=product.id,
            size="M",
            quantity=5,
            barcode="1234567890123",
        )
        session.add(size)
        session.flush()
        session.add(
            AllegroOffer(
                offer_id="offer-1",
                title="Szelki na spacery",
                price=Decimal("129.99"),
                product_id=product.id,
                product_size_id=size.id,
            )
        )

    response = client.get("/allegro/offers")

    body = response.data.decode("utf-8")
    assert body.count("<table") == 2
    assert "Oferty wymagające przypięcia" in body
    assert "Oferty powiązane z magazynem" in body
    assert "data-search-input" in body or "x-ref=\"searchInput\"" in body
    assert "Brak powiazania" in body
    assert "Szelki spacerowe" in body
    assert "EAN: 1234567890123" in body
    assert 'name="product_id"' in body
    assert "selectOption(" in body


def test_offers_and_prices_page_shows_searchable_mapping_dropdown(client, login):
    with get_session() as session:
        product = Product(name="Szelki treningowe", color="Zielone")
        session.add(product)
        session.flush()
        size = ProductSize(
            product_id=product.id,
            size="L",
            quantity=8,
            barcode="5901234567890",
        )
        session.add(size)
        session.flush()
        session.add(
            AllegroOffer(
                offer_id="offer-prices-1",
                title="Szelki treningowe Allegro",
                price=Decimal("149.99"),
                product_id=product.id,
                product_size_id=size.id,
                ean="5901234567890",
            )
        )

    response = client.get("/offers-and-prices")

    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "Szukaj produktu lub EAN..." in body
    assert 'class="modal"' in body
    assert "showModal()" in body
    assert 'x-model="searchQuery"' in body
    assert "Powiaz oferte z magazynem" in body
    assert "Brak pozycji pasujacych do wyszukiwania." in body
    assert "bg-base-100" in body
    assert "Szelki treningowe" in body
    assert "EAN: 5901234567890" in body


def test_offers_and_prices_page_links_offer_after_fetching_ean(client, login, monkeypatch):
    with get_session() as session:
        product = Product(name="Amortyzator do smyczy dla średniego psa", color="Żółty")
        session.add(product)
        session.flush()
        size = ProductSize(
            product_id=product.id,
            size="Uniwersalny",
            quantity=4,
            barcode="6971273115538",
        )
        session.add(size)
        session.flush()
        session.add(
            AllegroOffer(
                offer_id="offer-yellow-1",
                title="Amortyzator do smyczy dla średniego psa Truelove żółty",
                price=Decimal("89.99"),
                product_id=None,
                product_size_id=None,
                ean=None,
            )
        )

    monkeypatch.setattr(allegro_views, "_get_ean_for_offer", lambda offer_id: "6971273115538")

    response = client.get("/offers-and-prices")

    assert response.status_code == 200
    with get_session() as session:
        offer = session.query(AllegroOffer).filter_by(offer_id="offer-yellow-1").first()
        assert offer is not None
        assert offer.ean == "6971273115538"
        assert offer.product_id == product.id
        assert offer.product_size_id == size.id


def test_link_offer_to_product_size_updates_relation(client, login):
    with get_session() as session:
        product_current = Product(name="Smycz stara")
        product_target = Product(name="Smycz nowa", color="Granatowa")
        session.add_all([product_current, product_target])
        session.flush()

        size_target = ProductSize(
            product_id=product_target.id,
            size="L",
            quantity=3,
            barcode="ABC123",
        )
        session.add(size_target)
        session.flush()

        offer_id = "offer-2"
        session.add(
            AllegroOffer(
                offer_id=offer_id,
                title="Oferta Smyczy",
                price=Decimal("59.99"),
                product_id=product_current.id,
            )
        )

    response = client.post(
        f"/allegro/link/{offer_id}",
        data={"product_size_id": size_target.id},
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert body.count("<table") == 2
    unlinked_section = re.search(
        r'id="unlinked-offers".*?<tbody>(.*?)</tbody>', body, re.S
    )
    linked_section = re.search(
        r'id="linked-offers".*?<tbody>(.*?)</tbody>', body, re.S
    )
    assert unlinked_section and linked_section
    assert "Oferta Smyczy" not in unlinked_section.group(1)
    assert "Oferta Smyczy" in linked_section.group(1)

    with get_session() as session:
        updated = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id == offer_id)
            .one()
        )
        assert updated.product_size_id == size_target.id
        assert updated.product_id == product_target.id


def test_link_offer_to_product_updates_relation(client, login):
    with get_session() as session:
        product = Product(name="Obroża miejska", color="Czarna")
        session.add(product)
        session.flush()

        offer_id = "offer-3"
        session.add(
            AllegroOffer(
                offer_id=offer_id,
                title="Obroża bez rozmiaru",
                price=Decimal("39.99"),
            )
        )

    response = client.post(
        f"/allegro/link/{offer_id}",
        data={"product_id": product.id},
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.data.decode("utf-8")
    linked_section = re.search(
        r'id="linked-offers".*?<tbody>(.*?)</tbody>', body, re.S
    )
    assert linked_section
    assert "Obroża bez rozmiaru" in linked_section.group(1)
    assert "Obroża miejska" in linked_section.group(1)

    with get_session() as session:
        updated = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id == offer_id)
            .one()
        )
        assert updated.product_id == product.id
        assert updated.product_size_id is None


def test_offers_without_inventory_are_listed_first(client, login):
    with get_session() as session:
        product_a = Product(name="Produkt A")
        product_b = Product(name="Produkt B")
        session.add_all([product_a, product_b])
        session.flush()

        size_a = ProductSize(product_id=product_a.id, size="S")
        size_b = ProductSize(product_id=product_b.id, size="M")
        session.add_all([size_a, size_b])
        session.flush()

        session.add_all(
            [
                AllegroOffer(
                    offer_id="offer-unlinked",
                    title="ZZZ Oferta bez przypisania",
                    price=Decimal("10.00"),
                ),
                AllegroOffer(
                    offer_id="offer-alpha",
                    title="AAA Oferta powiązana",
                    price=Decimal("20.00"),
                    product_size_id=size_a.id,
                    product_id=product_a.id,
                ),
                AllegroOffer(
                    offer_id="offer-omega",
                    title="OOO Oferta powiązana",
                    price=Decimal("30.00"),
                    product_size_id=size_b.id,
                    product_id=product_b.id,
                ),
            ]
        )

    response = client.get("/allegro/offers")
    body = response.data.decode("utf-8")

    unlinked_section = re.search(
        r'id="unlinked-offers".*?<tbody>(.*?)</tbody>', body, re.S
    )
    linked_section = re.search(
        r'id="linked-offers".*?<tbody>(.*?)</tbody>', body, re.S
    )
    assert unlinked_section and linked_section

    unlinked_rows = re.findall(r"<tr>(.*?)</tr>", unlinked_section.group(1), re.S)
    unlinked_titles = []
    for row in unlinked_rows:
        columns = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        # Table columns: 0=ID, 1=EAN, 2=Title, 3=Price, 4=Link
        if len(columns) >= 3:
            unlinked_titles.append(re.sub(r"\s+", " ", columns[2]).strip())

    assert unlinked_titles == ["ZZZ Oferta bez przypisania"]

    linked_rows = re.findall(r"<tr>(.*?)</tr>", linked_section.group(1), re.S)
    linked_titles = []
    for row in linked_rows:
        columns = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        # Table columns: 0=ID, 1=EAN, 2=Title, 3=Price, 4=Link
        if len(columns) >= 3:
            linked_titles.append(re.sub(r"\s+", " ", columns[2]).strip())

    assert linked_titles == sorted(linked_titles)


def test_fetch_product_listing_refreshes_token_on_unauthorized(monkeypatch, allegro_tokens):
    class FakeResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return self._data

    allegro_tokens("expired-token", "refresh-token")

    listing_payload = {
        "items": {
            "regular": [
                {
                    "id": "offer-1",
                    "seller": {"id": "seller-1"},
                    "sellingMode": {"price": {"amount": "10.00"}},
                }
            ]
        },
        "links": {},
    }

    responses = [FakeResponse(401, {}), FakeResponse(200, listing_payload)]
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append({"headers": headers.copy(), "params": params.copy()})
        return responses.pop(0)

    def fake_refresh(refresh_value):
        assert refresh_value == "refresh-token"
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

    monkeypatch.setattr("magazyn.allegro_api.offers.requests.get", fake_get)
    monkeypatch.setattr("magazyn.allegro_api.offers.refresh_token", fake_refresh)
    persisted = []

    from magazyn.allegro_api import offers as _offers_mod
    original_update = _offers_mod.update_allegro_tokens

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

    monkeypatch.setattr(
        "magazyn.allegro_api.offers.update_allegro_tokens", capture_tokens
    )

    offers = fetch_product_listing("1234567890123")

    assert len(calls) == 2
    assert calls[0]["headers"]["Authorization"] == "Bearer expired-token"
    assert calls[1]["headers"]["Authorization"] == "Bearer new-access"
    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") == "new-access"
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") == "new-refresh"
    assert persisted == [
        {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
    ]
    assert offers == [
        {
            "id": "offer-1",
            "seller": {"id": "seller-1"},
            "sellingMode": {"price": {"amount": "10.00"}},
        }
    ]


def test_fetch_product_listing_raises_runtime_error_when_refresh_unavailable(
    monkeypatch, allegro_tokens
):
    class FakeResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return self._data

    allegro_tokens("expired-token")

    responses = [FakeResponse(403, {})]
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append({"headers": headers.copy(), "params": params.copy()})
        return responses.pop(0)

    monkeypatch.setattr("magazyn.allegro_api.offers.requests.get", fake_get)

    with pytest.raises(RuntimeError, match="please re-authorize"):
        fetch_product_listing("1234567890123")

    assert len(calls) == 1
    assert calls[0]["headers"]["Authorization"] == "Bearer expired-token"


def test_fetch_product_listing_raises_when_refresh_fails(
    monkeypatch, allegro_tokens
):
    class FakeResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return self._data

    allegro_tokens("expired-token", "refresh-token")

    responses = [FakeResponse(401, {})]

    def fake_get(url, headers, params, timeout):
        return responses.pop(0)

    def failing_refresh(refresh_value):
        raise requests.exceptions.HTTPError(response=FakeResponse(400, {}))

    monkeypatch.setattr("magazyn.allegro_api.offers.requests.get", fake_get)
    monkeypatch.setattr("magazyn.allegro_api.offers.refresh_token", failing_refresh)

    with pytest.raises(RuntimeError, match="please re-authorize"):
        fetch_product_listing("1234567890123")


def test_fetch_product_listing_debug_logs_include_allegro_error_code(
    monkeypatch, allegro_tokens
):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.headers = {}
            self.text = json.dumps(payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return self._payload

    allegro_tokens("expired-token", None)

    responses = [
        FakeResponse(
            403,
            {
                "errors": [
                    {
                        "code": "ACCESS_DENIED",
                        "message": "Forbidden",
                        "details": "insufficient_scope",
                    }
                ]
            },
        )
    ]

    def fake_get(url, headers, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr("magazyn.allegro_api.offers.requests.get", fake_get)

    debug_calls: list[tuple[str, object]] = []

    def debug(label, value):
        debug_calls.append((label, value))

    with pytest.raises(RuntimeError, match="please re-authorize"):
        fetch_product_listing("1234567890123", debug=debug)

    debug_map = {label: value for label, value in debug_calls}
    error_payload = debug_map.get("Listing Allegro: otrzymano błąd HTTP")
    assert error_payload is not None
    assert error_payload["status_code"] == 403
    assert error_payload["error_code"] == "ACCESS_DENIED"
    assert error_payload["error_message"] == "Forbidden"
    assert error_payload["error_details"] == "insufficient_scope"
