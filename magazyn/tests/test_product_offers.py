from magazyn.models.allegro import AllegroOffer
from magazyn.models.products import ProductOffer, ProductSize
from magazyn.services.product_offers import (
    copy_catalog_offer_from_allegro,
    list_catalog_offers,
    offer_view,
)
from magazyn.tests.conftest import make_product


def _offer(db, product_id, offer_id, **kwargs):
    row = AllegroOffer(
        offer_id=offer_id,
        title=kwargs.get("title", "Szelki L"),
        price=199,
        product_id=product_id,
        product_size_id=kwargs.get("product_size_id"),
        publication_status=kwargs.get("publication_status", "ACTIVE"),
        description_html=kwargs.get("description_html"),
        image_urls=kwargs.get("image_urls"),
    )
    db.add(row)
    return row


def test_copy_prefers_active_offer_with_description(app_mod):
    with app_mod.get_session() as db:
        product = make_product(series="Premium")
        db.add(product)
        db.flush()
        product_id = product.id
        _offer(
            db,
            product_id,
            "ended",
            title="Stara",
            publication_status="ENDED",
            description_html="<p>stary opis</p>",
            image_urls='["https://cdn.example/old.jpg"]',
        )
        _offer(
            db,
            product_id,
            "live",
            title="Szelki Premium L",
            description_html="<p>opis aktualny</p>",
            image_urls='["https://cdn.example/a.jpg"]',
        )
        db.commit()

    assert copy_catalog_offer_from_allegro(product_id) == "ok"

    with app_mod.get_session() as db:
        stored = db.query(ProductOffer).filter_by(product_id=product_id).one()
        view = offer_view(stored)
        assert view["title"] == "Szelki Premium L"
        assert view["has_description"]
        assert view["image_urls"] == ["https://cdn.example/a.jpg"]
        assert stored.source == "allegro"
        assert stored.allegro_offer_id == "live"


def test_copy_ignores_allegro_404_placeholder(app_mod):
    with app_mod.get_session() as db:
        product = make_product(series="Front Line")
        db.add(product)
        db.flush()
        product_id = product.id
        _offer(db, product_id, "empty", description_html="<!-- allegro-404 -->", image_urls="[]")
        db.commit()

    assert copy_catalog_offer_from_allegro(product_id) == "no_content"
    with app_mod.get_session() as db:
        assert db.query(ProductOffer).filter_by(product_id=product_id).count() == 0


def test_offers_page_lists_product_without_content(app_mod, client, login):
    with app_mod.get_session() as db:
        product = make_product(series="Adventure")
        db.add(product)
        db.flush()
        db.add(ProductSize(product_id=product.id, size="L", quantity=1, barcode="999"))
        db.commit()
        product_id = product.id

    response = client.get("/oferty")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Adventure" in body
    assert "Do uzupełnienia" not in body
    assert "brak" in body

    detail = client.get(f"/product/{product_id}")
    assert detail.status_code == 200
    assert "Edytuj ofertę" in detail.get_data(as_text=True)

    rows = list_catalog_offers("adventure")
    assert len(rows) == 1
    assert rows[0]["ready"] is False
