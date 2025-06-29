from magazyn.app import app
from magazyn.models import Product, ProductSize, Sale


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

