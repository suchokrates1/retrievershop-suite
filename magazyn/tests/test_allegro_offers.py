import os
from decimal import Decimal
import re

import pytest
import requests

from magazyn.config import settings
from magazyn.db import get_session
from magazyn.models import AllegroOffer, Product, ProductSize
from magazyn.allegro_api import fetch_product_listing


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
    assert "data-search-input" in body
    assert "Brak powiązania" in body
    assert "Szelki spacerowe" in body
    assert "EAN: 1234567890123" in body
    assert 'name="product_id"' in body
    assert 'data-kind="product"' in body


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
        if len(columns) >= 2:
            unlinked_titles.append(re.sub(r"\s+", " ", columns[1]).strip())

    assert unlinked_titles == ["ZZZ Oferta bez przypisania"]

    linked_rows = re.findall(r"<tr>(.*?)</tr>", linked_section.group(1), re.S)
    linked_titles = []
    for row in linked_rows:
        columns = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(columns) >= 2:
            linked_titles.append(re.sub(r"\s+", " ", columns[1]).strip())

    assert linked_titles == sorted(linked_titles)


def test_price_check_table_and_lowest_flag(client, login, monkeypatch):
    with get_session() as session:
        product = Product(name="Szelki", color="Niebieskie")
        session.add(product)
        session.flush()

        size_low = ProductSize(
            product_id=product.id,
            size="M",
            quantity=2,
            barcode="111",
        )
        size_high = ProductSize(
            product_id=product.id,
            size="L",
            quantity=3,
            barcode="222",
        )
        session.add_all([size_low, size_high])
        session.flush()

        session.add_all(
            [
                AllegroOffer(
                    offer_id="offer-low",
                    title="Oferta najtańsza",
                    price=Decimal("90.00"),
                    product_id=product.id,
                    product_size_id=size_low.id,
                ),
                AllegroOffer(
                    offer_id="offer-high",
                    title="Oferta droższa",
                    price=Decimal("120.00"),
                    product_id=product.id,
                    product_size_id=size_high.id,
                ),
            ]
        )

    monkeypatch.setattr(settings, "ALLEGRO_SELLER_ID", "our-seller")
    monkeypatch.setattr(settings, "ALLEGRO_EXCLUDED_SELLERS", set())

    def fake_listing(barcode):
        if barcode == "111":
            return [
                {
                    "seller": {"id": "our-seller"},
                    "sellingMode": {"price": {"amount": "90.00"}},
                },
                {
                    "seller": {"id": "competitor-a"},
                    "sellingMode": {"price": {"amount": "95.00"}},
                },
                {
                    "seller": {"id": "competitor-b"},
                    "sellingMode": {"price": {"amount": "110.00"}},
                },
            ]
        if barcode == "222":
            return [
                {
                    "seller": {"id": "competitor-c"},
                    "sellingMode": {"price": {"amount": "80.00"}},
                },
                {
                    "seller": {"id": "competitor-d"},
                    "sellingMode": {"price": {"amount": "125.00"}},
                },
            ]
        return []

    monkeypatch.setattr("magazyn.allegro.fetch_product_listing", fake_listing)

    response = client.get("/allegro/price-check")
    assert response.status_code == 200

    body = response.data.decode("utf-8")
    assert "Monitor cen Allegro" in body
    assert "Najniższa cena konkurencji" in body

    rows = re.findall(r"<tr>.*?</tr>", body, re.S)
    data_rows = [row for row in rows if "Oferta" in row and "th" not in row]
    row_low = next(row for row in data_rows if "Oferta najtańsza" in row)
    row_high = next(row for row in data_rows if "Oferta droższa" in row)

    assert "90.00 zł" in row_low
    assert "95.00 zł" in row_low
    assert "text-success" in row_low and "✓" in row_low

    assert "120.00 zł" in row_high
    assert "80.00 zł" in row_high
    assert "text-danger" in row_high and "✗" in row_high


def test_fetch_product_listing_refreshes_token_on_unauthorized(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return self._data

    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "expired-token")
    monkeypatch.setenv("ALLEGRO_REFRESH_TOKEN", "refresh-token")

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
        return {"access_token": "new-access", "refresh_token": "new-refresh"}

    monkeypatch.setattr("magazyn.allegro_api.requests.get", fake_get)
    monkeypatch.setattr("magazyn.allegro_api.refresh_token", fake_refresh)

    offers = fetch_product_listing("1234567890123")

    assert len(calls) == 2
    assert calls[0]["headers"]["Authorization"] == "Bearer expired-token"
    assert calls[1]["headers"]["Authorization"] == "Bearer new-access"
    assert os.getenv("ALLEGRO_ACCESS_TOKEN") == "new-access"
    assert os.getenv("ALLEGRO_REFRESH_TOKEN") == "new-refresh"
    assert offers == [
        {
            "id": "offer-1",
            "seller": {"id": "seller-1"},
            "sellingMode": {"price": {"amount": "10.00"}},
        }
    ]


def test_fetch_product_listing_raises_runtime_error_when_refresh_unavailable(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return self._data

    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "expired-token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)

    responses = [FakeResponse(403, {})]
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append({"headers": headers.copy(), "params": params.copy()})
        return responses.pop(0)

    monkeypatch.setattr("magazyn.allegro_api.requests.get", fake_get)

    with pytest.raises(RuntimeError, match="please re-authorize"):
        fetch_product_listing("1234567890123")

    assert len(calls) == 1
    assert calls[0]["headers"]["Authorization"] == "Bearer expired-token"
