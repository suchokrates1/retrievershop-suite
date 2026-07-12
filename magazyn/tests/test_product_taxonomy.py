import pytest

from magazyn.models.products import Product
from magazyn.services.product_taxonomy import (
    NEW_TAXONOMY_VALUE,
    distinct_brands,
    distinct_categories,
    distinct_series,
    resolve_optional_series,
    resolve_taxonomy_value,
    taxonomy_options,
)
from magazyn.tests.conftest import make_product


def test_distinct_values_from_database(app_mod):
    with app_mod.get_session() as db:
        db.add(make_product(category="Pas samochodowy", brand="Truelove", series="Premium"))
        db.add(make_product(category="Szelki", brand="Ruffwear", series="Front Line"))
        db.commit()

    assert "Pas samochodowy" in distinct_categories()
    assert "Szelki" in distinct_categories()
    assert "Ruffwear" in distinct_brands()
    assert "Premium" in distinct_series()
    assert "Front Line" in distinct_series()


def test_taxonomy_options_includes_current_value():
    options = taxonomy_options(["Szelki", "Smycz"], "Pas samochodowy")
    assert options == ["Pas samochodowy", "Smycz", "Szelki"]


def test_resolve_taxonomy_value_from_list_or_custom():
    assert resolve_taxonomy_value("Szelki", None) == "Szelki"
    assert resolve_taxonomy_value(NEW_TAXONOMY_VALUE, "  Nowa kategoria  ") == "Nowa kategoria"

    with pytest.raises(ValueError, match="Podaj nową"):
        resolve_taxonomy_value(NEW_TAXONOMY_VALUE, "   ", field_label="kategorię")

    with pytest.raises(ValueError, match="Wybierz markę"):
        resolve_taxonomy_value("", None, required=True, field_label="markę")


def test_resolve_optional_series():
    assert resolve_optional_series("", None) is None
    assert resolve_optional_series("Premium", None) == "Premium"
    assert resolve_optional_series(NEW_TAXONOMY_VALUE, "Nowa seria") == "Nowa seria"
    assert resolve_optional_series(NEW_TAXONOMY_VALUE, "   ") is None


def test_add_item_with_new_taxonomy_values(app_mod, client, login):
    data_add = {
        "sizing_mode": "sized",
        "category": NEW_TAXONOMY_VALUE,
        "custom_category": "Pas samochodowy",
        "brand": NEW_TAXONOMY_VALUE,
        "custom_brand": "TestBrand",
        "series": NEW_TAXONOMY_VALUE,
        "custom_series": "TestSeries",
        "color": "Czarny",
        "quantity_M": "1",
    }
    resp = client.post("/add_item", data=data_add)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        prod = db.query(Product).filter_by(category="Pas samochodowy", series="TestSeries").first()
        assert prod is not None
        assert prod.brand == "TestBrand"


def test_edit_item_get_shows_db_taxonomy(app_mod, client, login):
    with app_mod.get_session() as db:
        product = make_product(
            category="Pas samochodowy",
            brand="Truelove",
            series="Premium",
            color="Czarny",
        )
        db.add(product)
        db.commit()
        pid = product.id

    resp = client.get(f"/edit_item/{pid}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Pas samochodowy" in html
    assert "Premium" in html
    assert "+ Nowa kategoria..." in html
    assert "Chłodząca" not in html  # stala seria z constants.py
