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
    app_mod.consume_stock(pid, "M", 1)
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
    app_mod.consume_stock(pid, "M", 1)
    with app_mod.get_session() as db:
        sale = db.query(Sale).first()
        sale.sale_price = 120.0
        sale.shipping_cost = 0.0
        sale.commission_fee = 0.0
    resp = client.get("/sales")
    html = resp.get_data(as_text=True)
    assert "110.00" in html


def test_sale_recorded_without_purchase(app_mod, client, login):
    with app_mod.get_session() as db:
        prod = Product(name="ProdN", color="Black")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

    # consume stock when no purchases exist
    app_mod.consume_stock(pid, "M", 2)

    with app_mod.get_session() as db:
        sale = db.query(Sale).first()
        assert sale is not None
        assert sale.quantity == 2
        assert sale.purchase_cost == 0.0

    resp = client.get("/sales")
    text = resp.get_data(as_text=True)
    assert "ProdN (Black) M" in text
