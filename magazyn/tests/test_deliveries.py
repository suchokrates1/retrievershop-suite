from sqlalchemy import text
from werkzeug.datastructures import MultiDict
from magazyn.models import Product, ProductSize


def test_record_delivery(app_mod):
    with app_mod.get_session() as db:
        prod = Product(category="Zabawki", brand="Test", series="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

    # Note: add_delivery expects lists via getlist(), so we need list values
    data = MultiDict([
        ("ean", ""),  # Empty EAN to fall through to product_id/size selection
        ("product_id", str(pid)),
        ("size", "M"),
        ("quantity", "3"),
        ("price", "4.5"),
    ])
    with app_mod.app.test_request_context(
        "/deliveries", method="POST", data=data
    ):
        from flask import session

        session["username"] = "x"
        from magazyn import products

        products.add_delivery.__wrapped__()

    with app_mod.get_session() as db:
        batch = db.execute(
            text(
                "SELECT quantity, price FROM purchase_batches WHERE product_id=:pid AND size=:size"
            ),
            {"pid": pid, "size": "M"},
        ).fetchone()
        qty = db.execute(
            text(
                "SELECT quantity FROM product_sizes WHERE product_id=:pid AND size=:size"
            ),
            {"pid": pid, "size": "M"},
        ).fetchone()
    assert batch[0] == 3
    assert abs(float(batch[1]) - 4.5) < 0.001
    assert qty[0] == 3


def test_record_multiple_deliveries(app_mod):
    with app_mod.get_session() as db:
        prod = Product(category="Zabawki", brand="Test", series="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add_all(
            [
                ProductSize(product_id=prod.id, size="M", quantity=0),
                ProductSize(product_id=prod.id, size="L", quantity=0),
            ]
        )
        pid = prod.id

    # Note: add_delivery expects lists via getlist(), need empty ean entries
    data = MultiDict(
        [
            ("ean", ""),
            ("product_id", str(pid)),
            ("size", "M"),
            ("quantity", "2"),
            ("price", "1.5"),
            ("ean", ""),
            ("product_id", str(pid)),
            ("size", "L"),
            ("quantity", "1"),
            ("price", "2.0"),
        ]
    )
    with app_mod.app.test_request_context(
        "/deliveries", method="POST", data=data
    ):
        from flask import session

        session["username"] = "x"
        from magazyn import products

        products.add_delivery.__wrapped__()

    with app_mod.get_session() as db:
        m = db.execute(
            text(
                "SELECT quantity, price FROM purchase_batches WHERE product_id=:pid AND size='M'"
            ),
            {"pid": pid},
        ).fetchone()
        l = db.execute(
            text(
                "SELECT quantity, price FROM purchase_batches WHERE product_id=:pid AND size='L'"
            ),
            {"pid": pid},
        ).fetchone()
        qty_m = db.execute(
            text(
                "SELECT quantity FROM product_sizes WHERE product_id=:pid AND size='M'"
            ),
            {"pid": pid},
        ).scalar()
        qty_l = db.execute(
            text(
                "SELECT quantity FROM product_sizes WHERE product_id=:pid AND size='L'"
            ),
            {"pid": pid},
        ).scalar()
    assert m[0] == 2 and abs(float(m[1]) - 1.5) < 0.001
    assert l[0] == 1 and abs(float(l[1]) - 2.0) < 0.001
    assert qty_m == 2
    assert qty_l == 1


def test_consume_stock_fifo(app_mod):
    """Test FIFO stock consumption - oldest batches consumed first."""
    with app_mod.get_session() as db:
        prod = Product(category="Zabawki", brand="Test", series="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

    # First purchase: 2 items at 5.0
    app_mod.record_purchase(pid, "M", 2, 5.0)
    # Second purchase: 1 item at 4.0
    app_mod.record_purchase(pid, "M", 1, 4.0)
    
    # Consume 2 items - FIFO means oldest batch (5.0) is depleted first
    consumed = app_mod.consume_stock(pid, "M", 2, sale_price=0)

    with app_mod.get_session() as db:
        qty = db.execute(
            text(
                "SELECT quantity FROM product_sizes WHERE product_id=:pid AND size=:size"
            ),
            {"pid": pid, "size": "M"},
        ).fetchone()[0]
        # Get only non-depleted batches (quantity > 0)
        batches = db.execute(
            text(
                "SELECT price, quantity FROM purchase_batches "
                "WHERE product_id=:pid AND size=:size AND quantity > 0 ORDER BY price"
            ),
            {"pid": pid, "size": "M"},
        ).fetchall()
    assert consumed == 2
    assert qty == 1  # 3 total - 2 consumed = 1 remaining
    assert len(batches) == 1
    # FIFO: oldest batch (5.0) depleted, newer batch (4.0) remains
    assert float(batches[0][0]) == 4.0
    assert batches[0][1] == 1


def test_deliveries_page_shows_color(app_mod):
    with app_mod.get_session() as db:
        prod = Product(category="Zabawki", brand="Test", series="Prod", color="Blue")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=1))

    with app_mod.app.test_request_context("/deliveries"):
        from flask import session

        session["username"] = "tester"
        from magazyn import products

        html = products.add_delivery.__wrapped__()
    assert "Prod (Blue)" in html
