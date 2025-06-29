from magazyn.models import Product, ProductSize, Sale


def test_sales_page_lists_entries(app_mod, client, login):
    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=1))
        db.add(
            Sale(
                product_id=prod.id,
                size="M",
                purchase_price=1.5,
                sale_price=3.0,
                shipping_cost=2.0,
                commission=0.5,
                platform="shop",
                sale_date="2023-01-01T00:00:00",
            )
        )
    resp = client.get("/sales")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Prod" in html
    assert "Red" in html
    assert "M" in html
    assert "3.00" in html
    assert "shop" in html
