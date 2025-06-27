import importlib
from magazyn.models import ProductSize, Product


def load_services():
    srv = importlib.import_module("magazyn.services")
    return importlib.reload(srv)


def test_create_and_list(app_mod):
    services = load_services()
    services.create_product("Prod", "Red", {"M": 2}, {"M": "111"})
    items = services.list_products()
    assert items[0]["name"] == "Prod"
    assert items[0]["sizes"]["M"] == 2


def test_update_and_get_details(app_mod):
    services = load_services()
    prod = services.create_product("Prod", "Red", {"M": 1}, {"M": "111"})
    services.update_product(prod.id, "Prod2", "Blue", {"M": 5}, {"M": "222"})
    info, sizes = services.get_product_details(prod.id)
    assert info["name"] == "Prod2"
    assert sizes["M"]["quantity"] == 5
    assert sizes["M"]["barcode"] == "222"


def test_delete_product(app_mod):
    services = load_services()
    prod = services.create_product("Prod", "Red", {"M": 1}, {"M": "111"})
    services.delete_product(prod.id)
    with app_mod.get_session() as db:
        assert db.query(Product).filter_by(id=prod.id).first() is None


def test_update_quantity_increase(app_mod):
    services = load_services()
    prod = services.create_product("Prod", "Red", {"M": 1}, {"M": "111"})
    services.update_quantity(prod.id, "M", "increase")
    info, sizes = services.get_product_details(prod.id)
    assert sizes["M"]["quantity"] == 2


def test_record_delivery(app_mod):
    services = load_services()
    prod = services.create_product("Prod", "Red", {"M": 0}, {"M": "111"})
    services.record_delivery(prod.id, "M", 3, 4.5)
    info, sizes = services.get_product_details(prod.id)
    assert sizes["M"]["quantity"] == 3
    with app_mod.get_session() as db:
        ps = db.query(ProductSize).filter_by(product_id=prod.id, size="M").first()
        assert ps.quantity == 3


def test_find_by_barcode(app_mod):
    services = load_services()
    prod = services.create_product("Prod", "Green", {"M": 1}, {"M": "999"})
    result = services.find_by_barcode("999")
    assert result == {"name": "Prod", "color": "Green", "size": "M"}

