import magazyn.allegro_sync as sync_mod
from decimal import Decimal

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

