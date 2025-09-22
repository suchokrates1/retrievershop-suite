import re
from decimal import Decimal

import pytest
from magazyn.db import get_session
from magazyn.models import AllegroOffer, Product, ProductSize


@pytest.mark.usefixtures("login")
class TestAllegroPriceCheckDebug:
    def test_price_check_html_displays_debug_steps(
        self, client, allegro_tokens
    ) -> None:
        allegro_tokens("token", "refresh")

        response = client.get("/allegro/price-check")
        assert response.status_code == 200

        body = response.data.decode("utf-8")
        assert "Szczegóły diagnostyczne" in body
        assert "Czy dostępny access token Allegro" in body
        # Value rendered within <pre> tag
        assert re.search(r"<pre[^>]*>True</pre>", body)

    def test_price_check_json_includes_debug_steps_on_success(
        self, client, allegro_tokens, monkeypatch
    ) -> None:
        allegro_tokens("token", "refresh")
        with get_session() as session:
            product = Product(name="Szelki", color="Niebieskie")
            session.add(product)
            session.flush()
            size = ProductSize(
                product_id=product.id,
                size="M",
                barcode="321",
            )
            session.add(size)
            session.flush()
            session.add(
                AllegroOffer(
                    offer_id="offer-debug",
                    title="Oferta debug",
                    price=Decimal("123.00"),
                    product_size_id=size.id,
                )
            )

        def fake_listing(barcode, *, debug=None):
            if debug is not None:
                debug("Testowy listing", {"ean": barcode})
            return [
                {
                    "id": "competitor-offer",
                    "seller": {"id": "competitor"},
                    "sellingMode": {"price": {"amount": "120.00"}},
                }
            ]

        monkeypatch.setattr("magazyn.allegro.fetch_product_listing", fake_listing)

        response = client.get("/allegro/price-check?format=json")
        assert response.status_code == 200

        payload = response.get_json()
        assert payload["auth_error"] is None
        assert payload["price_checks"]
        labels = [step["label"] for step in payload["debug_steps"]]
        assert "Testowy listing" in labels
        assert "Listing Allegro – liczba ofert" in labels

    def test_price_check_json_reports_refresh_error_steps(
        self, client, allegro_tokens, monkeypatch
    ) -> None:
        allegro_tokens("token", "refresh")
        with get_session() as session:
            product = Product(name="Obroża")
            session.add(product)
            session.flush()
            size = ProductSize(product_id=product.id, size="L", barcode="654")
            session.add(size)
            session.flush()
            session.add(
                AllegroOffer(
                    offer_id="offer-error",
                    title="Oferta z błędem",
                    price=Decimal("150.00"),
                    product_size_id=size.id,
                )
            )

        def failing_listing(barcode, *, debug=None):
            if debug is not None:
                debug("Listing Allegro: odświeżanie nieudane", "Błąd testowy")
            raise RuntimeError(
                "Failed to refresh Allegro access token for product listing; "
                "please re-authorize the Allegro integration"
            )

        monkeypatch.setattr("magazyn.allegro.fetch_product_listing", failing_listing)

        response = client.get("/allegro/price-check?format=json")
        assert response.status_code == 200

        payload = response.get_json()
        assert payload["auth_error"] is None
        assert payload["price_checks"]
        item = payload["price_checks"][0]
        assert "Failed to refresh Allegro access token" in item["error"]
        labels = [step["label"] for step in payload["debug_steps"]]
        assert "Listing Allegro: odświeżanie nieudane" in labels
        assert "Błąd pobierania listingu Allegro" in labels
