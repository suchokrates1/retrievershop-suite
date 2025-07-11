from magazyn.app import app
from magazyn.models import Product, ProductSize, Sale, ShippingThreshold


def test_sales_page_get(app_mod, client, login):
    resp = client.get("/sales")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Sprzedaż" in html


def test_sales_profit_calculated(app_mod, client, login):
    # create product and sale
    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Blue")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id
    app_mod.record_purchase(pid, "M", 1, 10.0)
    app_mod.consume_stock(pid, "M", 1, sale_price=0)
    with app_mod.get_session() as db:
        sale = db.query(Sale).first()
        sale.sale_price = 20.0
        sale.shipping_cost = 5.0
        sale.commission_fee = 2.0
    resp = client.get("/sales")
    html = resp.get_data(as_text=True)
    assert "3.00" in html


def test_profit_uses_threshold(app_mod, client, login):
    with app_mod.get_session() as db:
        prod = Product(name="ProdT", color="Green")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id
        db.add_all(
            [
                ShippingThreshold(min_order_value=0.0, shipping_cost=8.0),
                ShippingThreshold(min_order_value=100.0, shipping_cost=0.0),
            ]
        )
    app_mod.record_purchase(pid, "M", 1, 10.0)
    app_mod.consume_stock(pid, "M", 1, sale_price=0)
    with app_mod.get_session() as db:
        sale = db.query(Sale).first()
        sale.sale_price = 120.0
        sale.shipping_cost = 0.0
        sale.commission_fee = 0.0
    resp = client.get("/sales")
    html = resp.get_data(as_text=True)
    assert "110.00" in html


def test_consume_stock_records_sale_without_inventory(app_mod):
    with app_mod.get_session() as db:
        prod = Product(name="Ghost", color="")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

    consumed = app_mod.consume_stock(pid, "M", 2, sale_price=0)

    assert consumed == 0
    with app_mod.get_session() as db:
        sale = db.query(Sale).first()
        assert sale.product_id == pid
        assert sale.quantity == 2
        assert sale.purchase_cost == 0.0


def test_sales_page_shows_unknown_for_unmatched_order(app_mod, client, login):
    import importlib

    services = importlib.import_module("magazyn.services")
    importlib.reload(services)

    services.consume_order_stock(
        [
            {
                "name": "Nonexistent",
                "quantity": 1,
                "attributes": [{"name": "size", "value": "M"}],
            }
        ]
    )

    resp = client.get("/sales")
    html = resp.get_data(as_text=True)
    assert "Unknown" in html

def test_consume_order_stock_parses_name_for_match(app_mod):
    import importlib
    services = importlib.import_module("magazyn.services")
    importlib.reload(services)

    with app_mod.get_session() as db:
        prod = Product(name="Szelki dla psa Truelove Front Line Premium", color="Czarny")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=1))
        pid = prod.id
    app_mod.record_purchase(pid, "M", 1, 10.0)

    services.consume_order_stock(
        [
            {
                "name": "Szelki dla psa Truelove Front Line Premium M czarne",
                "quantity": 1,
                "attributes": [],
            }
        ]
    )

    with app_mod.get_session() as db:
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=pid, size="M")
            .one()
        )
        assert ps.quantity == 1
        sale = db.query(Sale).first()
        assert sale.product_id == pid
        assert sale.size == "M"
        assert sale.quantity == 1


def test_consume_order_stock_records_sale_price(app_mod, client, login):
    import importlib
    services = importlib.import_module("magazyn.services")
    importlib.reload(services)

    with app_mod.get_session() as db:
        prod = Product(name="Priced", color="Orange")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=1))
        pid = prod.id

    app_mod.record_purchase(pid, "M", 1, 10.0)

    services.consume_order_stock(
        [
            {
                "name": "Priced",
                "quantity": 1,
                "attributes": [{"name": "size", "value": "M"}],
                "price_brutto": 50.0,
            }
        ]
    )

    with app_mod.get_session() as db:
        sale = db.query(Sale).first()
        assert sale.sale_price == 50.0

    resp = client.get("/sales")
    html = resp.get_data(as_text=True)
    assert "50.00" in html
