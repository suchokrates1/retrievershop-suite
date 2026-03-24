from magazyn.models import ProductSize, Product
from magazyn.domain.products import (
    create_product,
    update_product,
    delete_product,
    get_product_details,
    list_products,
    find_by_barcode,
)
from magazyn.domain.inventory import record_delivery, update_quantity


def _create(name, color, quantities, barcodes):
    return create_product(
        category=name, brand="Truelove", series=None,
        color=color, quantities=quantities, barcodes=barcodes,
    )


def test_create_and_list(app_mod):
    _create("Prod", "Red", {"M": 2}, {"M": "11100000"})
    items = list_products()
    assert items[0]["category"] == "Prod"
    assert items[0]["sizes"]["M"] == 2


def test_update_and_get_details(app_mod):
    prod = _create("Prod", "Red", {"M": 1}, {"M": "11100000"})
    update_product(
        prod.id, category="Prod2", brand="Truelove", series=None,
        color="Blue", quantities={"M": 5}, barcodes={"M": "22200000"},
    )
    info, sizes = get_product_details(prod.id)
    assert info["category"] == "Prod2"
    assert sizes["M"]["quantity"] == 5
    assert sizes["M"]["barcode"] == "22200000"


def test_delete_product(app_mod):
    prod = _create("Prod", "Red", {"M": 1}, {"M": "11100000"})
    delete_product(prod.id)
    with app_mod.get_session() as db:
        assert db.query(Product).filter_by(id=prod.id).first() is None


def test_update_quantity_increase(app_mod):
    prod = _create("Prod", "Red", {"M": 1}, {"M": "11100000"})
    update_quantity(prod.id, "M", "increase")
    info, sizes = get_product_details(prod.id)
    assert sizes["M"]["quantity"] == 2


def test_update_quantity_decrease_without_batches(app_mod):
    prod = _create("Prod", "Red", {"M": 1}, {"M": "11100000"})
    update_quantity(prod.id, "M", "decrease")
    info, sizes = get_product_details(prod.id)
    assert sizes["M"]["quantity"] == 0


def test_record_delivery(app_mod):
    prod = _create("Prod", "Red", {"M": 0}, {"M": "11100000"})
    record_delivery(prod.id, "M", 3, 4.5)
    info, sizes = get_product_details(prod.id)
    assert sizes["M"]["quantity"] == 3
    with app_mod.get_session() as db:
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod.id, size="M")
            .first()
        )
        assert ps.quantity == 3


def test_find_by_barcode(app_mod):
    _create("Prod", "Green", {"M": 1}, {"M": "99900000"})
    result = find_by_barcode("99900000")
    assert result["category"] == "Prod"
    assert result["color"] == "Green"
    assert result["size"] == "M"
    assert "product_size_id" in result
