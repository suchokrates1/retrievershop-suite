import re
from decimal import Decimal

import pytest
from magazyn.config import settings
from magazyn.db import get_session
from magazyn.models import AllegroOffer, Product, ProductSize
from magazyn.allegro_scraper import Offer, AllegroScrapeError


@pytest.mark.usefixtures("login")
class TestAllegroPriceCheckDebug:
    def test_price_check_html_displays_debug_steps(
        self, client, allegro_tokens
    ) -> None:
        allegro_tokens("token", "refresh")

        response = client.get("/allegro/price-check")
        assert response.status_code == 200

        body = response.data.decode("utf-8")
        assert "Pełne logi price-check" in body
        assert "id=\"price-check-log-content\"" in body
        assert "Żądany format odpowiedzi" in body
        # Value rendered within <pre> tag
        assert re.search(r"<pre[^>]*>html</pre>", body)

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

        def fake_competitors(
            offer_id, *, stop_seller=None, limit=30, headless=True, log_callback=None
        ):
            if stop_seller:
                assert stop_seller == settings.ALLEGRO_SELLER_NAME
            if log_callback is not None:
                log_callback("Testowy listing")
            return (
                [
                    Offer(
                        "Konkurent",
                        "120,00 zł",
                        "Sklep",
                        "https://allegro.pl/oferta/competitor-offer",
                    )
                ],
                ["Testowy listing"],
            )

        monkeypatch.setattr("magazyn.allegro.fetch_competitors_for_offer", fake_competitors)

        response = client.get("/allegro/price-check?format=json")
        assert response.status_code == 200

        payload = response.get_json()
        assert payload["auth_error"] is None
        assert payload["price_checks"]
        labels = [step["label"] for step in payload["debug_steps"]]
        assert "Log Selenium" in labels
        assert "Oferty konkurencji – liczba ofert" in labels
        assert "Log Selenium" in payload["debug_log"]
        assert "Testowy listing" in payload["debug_log"]

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

        def failing_competitors(
            offer_id, *, stop_seller=None, limit=30, headless=True, log_callback=None
        ):
            if log_callback is not None:
                log_callback("Start Selenium")
            raise AllegroScrapeError(
                "Selenium error: brak danych",
                ["Start Selenium", "Zamykanie przeglądarki Selenium"],
            )

        monkeypatch.setattr("magazyn.allegro.fetch_competitors_for_offer", failing_competitors)

        response = client.get("/allegro/price-check?format=json")
        assert response.status_code == 200

        payload = response.get_json()
        assert payload["auth_error"] is None
        assert payload["price_checks"]
        item = payload["price_checks"][0]
        assert "Selenium error" in item["error"]
        labels = [step["label"] for step in payload["debug_steps"]]
        assert "Błąd pobierania ofert Allegro" in labels
        assert "Log Selenium" in labels
        assert "Błąd pobierania ofert Allegro" in payload["debug_log"]
        assert "Start Selenium" in payload["debug_log"]

    def test_price_check_stream_emits_events(
        self, client, allegro_tokens, monkeypatch
    ) -> None:
        allegro_tokens("token", "refresh")
        with get_session() as session:
            product = Product(name="Smycz")
            session.add(product)
            session.flush()
            size = ProductSize(product_id=product.id, size="XL", barcode="987")
            session.add(size)
            session.flush()
            session.add(
                AllegroOffer(
                    offer_id="offer-stream",
                    title="Oferta stream",
                    price=Decimal("75.00"),
                    product_size_id=size.id,
                )
            )

        def fake_competitors(
            offer_id, *, stop_seller=None, limit=30, headless=True, log_callback=None
        ):
            if log_callback is not None:
                log_callback("Stream log")
            return (
                [],
                ["Stream log"],
            )

        monkeypatch.setattr("magazyn.allegro.fetch_competitors_for_offer", fake_competitors)

        response = client.get("/allegro/price-check/stream")
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        body = response.get_data(as_text=True)
        assert "event: log" in body
        assert "Stream log" in body
        assert "event: result" in body
