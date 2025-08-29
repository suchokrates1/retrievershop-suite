import magazyn.allegro_sync as allegro_sync
from magazyn.db import get_session
from magazyn.models import Product, ProductSize, AllegroOffer


def test_sync_offers_creates_records(app_mod, monkeypatch):
    # Prepare product with barcode
    with get_session() as session:
        prod = Product(name="P", color="C")
        session.add(prod)
        session.flush()
        ps = ProductSize(product_id=prod.id, size="M", quantity=0, barcode="123")
        session.add(ps)

    # Setup fake API
    monkeypatch.setenv("ALLEGRO_REFRESH_TOKEN", "ref")
    monkeypatch.setattr(allegro_sync, "refresh_token", lambda token: {"access_token": "tok"})

    pages = [
        {"offers": [{"id": "1", "name": "Offer", "ean": "123"}]},
        {"offers": []},
    ]

    def fake_fetch(token, page=1):
        return pages[page - 1]

    monkeypatch.setattr(allegro_sync, "fetch_offers", fake_fetch)

    allegro_sync.sync_offers()

    with get_session() as session:
        offer = session.get(AllegroOffer, "1")
        assert offer is not None
        assert offer.product_size_id == ps.id
        assert offer.name == "Offer"
