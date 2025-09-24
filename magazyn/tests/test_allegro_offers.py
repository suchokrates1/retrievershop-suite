from decimal import Decimal
import re

import json

import pytest
import requests

import magazyn.allegro_api as allegro_api
from magazyn.settings_store import settings_store

from magazyn.config import settings
from magazyn.db import get_session
from magazyn.models import AllegroOffer, Product, ProductSize
from magazyn.allegro_api import fetch_product_listing
from magazyn.allegro_scraper import Offer


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


def test_price_check_does_not_require_allegro_authorization(
    client, login, allegro_tokens
):
    allegro_tokens()

    response = client.get("/allegro/price-check")
    assert response.status_code == 200

    body = response.data.decode("utf-8")
    assert (
        "Brak połączenia z Allegro. Kliknij „Połącz z Allegro” w ustawieniach, aby ponownie autoryzować aplikację."
        not in body
    )
    assert 'id="price-check-loading"' in body
    assert 'id="price-check-table-body"' in body

    json_response = client.get("/allegro/price-check?format=json")
    assert json_response.status_code == 200
    payload = json_response.get_json()
    assert payload["price_checks"] == []
    assert payload["auth_error"] is None
    assert isinstance(payload["debug_steps"], list)
    labels = [step["label"] for step in payload["debug_steps"]]
    assert "Żądany format odpowiedzi" in labels


def test_price_check_table_and_lowest_flag(client, login, monkeypatch, allegro_tokens):
    allegro_tokens("token", "refresh")
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

    monkeypatch.setattr(settings, "ALLEGRO_SELLER_NAME", "Retriever Shop")

    def fake_competitors(
        offer_id, *, stop_seller=None, limit=30, headless=True, log_callback=None
    ):
        if offer_id == "offer-low":
            if log_callback is not None:
                log_callback("Zatrzymano na sprzedawcy: Retriever Shop", None)
            return (
                [
                    Offer("Nasza oferta", "90,00 zł", "Retriever Shop", "https://allegro.pl/oferta/offer-low"),
                    Offer(
                        "Konkurent A",
                        "95,00 zł",
                        "A Sklep",
                        "https://allegro.pl/oferta/competitor-a-offer",
                    ),
                    Offer(
                        "Konkurent B",
                        "110,00 zł",
                        "B Sklep",
                        "https://allegro.pl/oferta/competitor-b-offer",
                    ),
                ],
                [
                    "Zatrzymano na sprzedawcy: Retriever Shop"
                ],
            )
        if offer_id == "offer-high":
            return (
                [
                    Offer(
                        "Konkurent C",
                        "80,00 zł",
                        "C Sklep",
                        "https://allegro.pl/oferta/competitor-c-offer",
                    ),
                    Offer(
                        "Konkurent D",
                        "125,00 zł",
                        "D Sklep",
                        "https://allegro.pl/oferta/competitor-d-offer",
                    ),
                ],
                [],
            )
        return ([], [])

    monkeypatch.setattr("magazyn.allegro.fetch_competitors_for_offer", fake_competitors)

    response = client.get("/allegro/price-check")
    assert response.status_code == 200

    body = response.data.decode("utf-8")
    assert "Monitor cen Allegro" in body
    assert 'id="price-check-loading"' in body
    assert 'id="price-check-table-body"' in body
    assert 'price_check.js' in body

    json_response = client.get("/allegro/price-check?format=json")
    assert json_response.status_code == 200

    payload = json_response.get_json()
    assert payload["auth_error"] is None
    assert isinstance(payload["debug_steps"], list)
    assert any(
        step["label"] == "Sprawdzanie ofert Allegro dla kodu kreskowego"
        for step in payload["debug_steps"]
    )
    assert len(payload["price_checks"]) == 2

    by_offer = {item["offer_id"]: item for item in payload["price_checks"]}

    low = by_offer["offer-low"]
    assert low["title"] == "Oferta najtańsza"
    assert low["own_price"] == "90.00"
    assert low["competitor_price"] == "95.00"
    assert low["competitor_offer_url"] == "https://allegro.pl/oferta/competitor-a-offer"
    assert low["is_lowest"] is True

    high = by_offer["offer-high"]
    assert high["title"] == "Oferta droższa"
    assert high["own_price"] == "120.00"
    assert high["competitor_price"] == "80.00"
    assert high["competitor_offer_url"] == "https://allegro.pl/oferta/competitor-c-offer"
    assert high["is_lowest"] is False


def test_price_check_product_level_aggregates_barcodes(client, login, monkeypatch, allegro_tokens):
    allegro_tokens("token", "refresh")
    with get_session() as session:
        product = Product(name="Legowisko", color="Szare")
        session.add(product)
        session.flush()

        size_small = ProductSize(
            product_id=product.id,
            size="S",
            barcode="333",
        )
        size_large = ProductSize(
            product_id=product.id,
            size="L",
            barcode="444",
        )
        session.add_all([size_small, size_large])
        session.flush()

        session.add(
            AllegroOffer(
                offer_id="offer-product",
                title="Oferta produktowa",
                price=Decimal("150.00"),
                product_id=product.id,
            )
        )

    monkeypatch.setattr(settings, "ALLEGRO_SELLER_NAME", None)

    called_offers: list[str] = []

    def fake_competitors(
        offer_id, *, stop_seller=None, limit=30, headless=True, log_callback=None
    ):
        called_offers.append(offer_id)
        if offer_id == "offer-product":
            if log_callback is not None:
                log_callback("Log dla 333", None)
                log_callback("Log dla 444", None)
            return (
                [
                    Offer(
                        "Konkurent 1",
                        "120,00 zł",
                        "Sklep 1",
                        "https://allegro.pl/oferta/competitor-1-offer",
                    ),
                    Offer(
                        "Konkurent 2",
                        "85,00 zł",
                        "Sklep 2",
                        "https://allegro.pl/oferta/competitor-2-offer",
                    ),
                ],
                [],
            )
        return ([], [])

    monkeypatch.setattr("magazyn.allegro.fetch_competitors_for_offer", fake_competitors)

    json_response = client.get("/allegro/price-check?format=json")
    assert json_response.status_code == 200

    payload = json_response.get_json()
    assert payload["auth_error"] is None
    assert isinstance(payload["debug_steps"], list)
    assert len(payload["price_checks"]) == 1

    item = payload["price_checks"][0]
    assert item["offer_id"] == "offer-product"
    assert item["label"] == "Legowisko Szare"
    assert item["competitor_price"] == "85.00"
    assert item["competitor_offer_url"] == "https://allegro.pl/oferta/competitor-2-offer"
    assert called_offers == ["offer-product"]


def test_fetch_product_listing_refreshes_token_on_unauthorized(monkeypatch, allegro_tokens):
    class FakeResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data

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

    monkeypatch.setattr("magazyn.allegro_api.requests.get", fake_get)
    monkeypatch.setattr("magazyn.allegro_api.refresh_token", fake_refresh)
    persisted = []

    original_update = allegro_api.update_allegro_tokens

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
        "magazyn.allegro_api.update_allegro_tokens", capture_tokens
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

    monkeypatch.setattr("magazyn.allegro_api.requests.get", fake_get)

    with pytest.raises(RuntimeError, match="please re-authorize"):
        fetch_product_listing("1234567890123")

    assert len(calls) == 1
    assert calls[0]["headers"]["Authorization"] == "Bearer expired-token"


def test_fetch_product_listing_clears_tokens_when_refresh_fails(
    monkeypatch, allegro_tokens
):
    class FakeResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return self._data

    allegro_tokens("expired-token", "refresh-token")

    responses = [FakeResponse(401, {})]

    def fake_get(url, headers, params, timeout):
        return responses.pop(0)

    clear_calls: list[bool] = []

    def fake_clear():
        clear_calls.append(True)
        allegro_tokens()

    def failing_refresh(refresh_value):
        raise requests.exceptions.HTTPError(response=FakeResponse(400, {}))

    monkeypatch.setattr("magazyn.allegro_api.requests.get", fake_get)
    monkeypatch.setattr("magazyn.allegro_api.refresh_token", failing_refresh)
    monkeypatch.setattr("magazyn.allegro_api.clear_allegro_tokens", fake_clear)

    with pytest.raises(RuntimeError, match="please re-authorize"):
        fetch_product_listing("1234567890123")

    assert clear_calls == [True]
    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") is None
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") is None


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

    monkeypatch.setattr("magazyn.allegro_api.requests.get", fake_get)

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
