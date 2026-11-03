from magazyn.domain.offer_templates import render_offer_html, template_for
from magazyn.models.allegro import AllegroOffer
from magazyn.models.products import ProductOffer
from magazyn.services.product_offers import compose_catalog_offer_from_template
from magazyn.tests.conftest import make_product


def test_premium_template_lists_size_table_and_color():
    template = template_for("Szelki", "Front Line Premium")
    html = render_offer_html(
        template,
        color="czerwony",
        photos=["https://cdn.example/a.jpg", "https://cdn.example/tabela-rozmiar.jpg"],
    )
    assert "Kolor:" in html and "czerwony" in html
    assert "do 4 kg" in html
    assert "Yorkshire Terrier" in html
    assert "do 38 kg" in html
    assert "3M Scotchlite" in html
    assert "auction-row-reverse" in html
    assert "tabela-rozmiar.jpg" in html
    assert "18–28" not in html
    assert "18-28" not in html


def test_single_size_render_drops_other_sizes():
    template = template_for("Szelki", "Front Line")
    html = render_offer_html(template, color="brązowy", photos=[], only_size="L")
    assert "do 27 kg" in html
    assert "Border Collie" in html
    assert "7–18 kg" not in html


def test_unknown_series_has_no_template():
    assert template_for("Szelki", "Nieistniejąca") is None


def test_compose_saves_template_for_product_color(app_mod):
    with app_mod.get_session() as db:
        product = make_product(category="Szelki", series="Front Line Premium", color="Czerwony")
        db.add(product)
        db.flush()
        product_id = product.id
        db.add(
            AllegroOffer(
                offer_id="prem-1",
                title="Szelki L",
                price=199,
                product_id=product_id,
                publication_status="ACTIVE",
                description_html="<p>stary opis z wagą 18-28 kg</p>",
                image_urls='["https://cdn.example/photo.jpg","https://cdn.example/size-chart.png"]',
            )
        )
        db.commit()

    assert compose_catalog_offer_from_template(product_id) == "ok"

    with app_mod.get_session() as db:
        stored = db.query(ProductOffer).filter_by(product_id=product_id).one()
        assert stored.source == "template"
        assert "Czerwony" in stored.title
        assert "do 4 kg" in stored.description_html
        assert "18-28" not in stored.description_html
        assert "size-chart.png" in stored.description_html
