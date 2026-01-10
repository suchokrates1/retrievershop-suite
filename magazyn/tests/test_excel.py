import pandas as pd
from io import BytesIO
from sqlalchemy import text
from magazyn.models import Product, ProductSize


def test_export_products_includes_barcode(app_mod, client, login):
    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(
            ProductSize(
                product_id=prod.id, size="M", quantity=5, barcode="123"
            )
        )

    resp = client.get("/export_products")

    df = pd.read_excel(BytesIO(resp.data))
    assert "Barcode" in df.columns
    assert str(df.loc[0, "Barcode"]) == "123"


def test_import_products_reads_barcode(app_mod, tmp_path):
    df = pd.DataFrame(
        [
            {
                "Nazwa": "Prod",
                "Kolor": "Red",
                "Barcode (XS)": "111",
                "Barcode (M)": "999",
                "Ilość (XS)": 1,
                "Ilość (S)": 0,
                "Ilość (M)": 2,
                "Ilość (L)": 0,
                "Ilość (XL)": 0,
                "Ilość (Uniwersalny)": 0,
            }
        ]
    )
    file_path = tmp_path / "import.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "import.xlsx")}
        with app_mod.app.test_request_context(
            "/import_products",
            method="POST",
            data=data,
            content_type="multipart/form-data",
        ):
            from flask import session

            session["username"] = "x"
            from magazyn import products

            products.import_products.__wrapped__()

    with app_mod.get_session() as db:
        row = db.execute(
            text(
                "SELECT ps.barcode FROM product_sizes ps JOIN products p ON ps.product_id = p.id WHERE p.name=:name AND p.color=:color AND ps.size='M'"
            ),
            {"name": "Prod", "color": "Red"},
        ).fetchone()
        assert row[0] == "999"


def test_import_products_handles_nan(app_mod, tmp_path):
    df = pd.DataFrame(
        [
            {
                "Nazwa": "ProdNaN",
                "Kolor": "Blue",
                "Ilość (XS)": 0,
                "Ilość (S)": 0,
                "Ilość (M)": 3,
                "Ilość (L)": float("nan"),
                "Ilość (XL)": 0,
                "Ilość (Uniwersalny)": 0,
            }
        ]
    )
    file_path = tmp_path / "import_nan.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "import_nan.xlsx")}
        with app_mod.app.test_request_context(
            "/import_products",
            method="POST",
            data=data,
            content_type="multipart/form-data",
        ):
            from flask import session

            session["username"] = "x"
            from magazyn import products

            products.import_products.__wrapped__()

    with app_mod.get_session() as db:
        prod = db.query(Product).filter(Product._name == "ProdNaN", Product.color == "Blue").first()
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod.id, size="L")
            .first()
        )
        assert ps.quantity == 0


def test_consume_stock_multiple_batches(app_mod):
    """Test FIFO consumption across multiple batches.
    
    FIFO = First In First Out: oldest batches consumed first by purchase_date.
    """
    with app_mod.get_session() as db:
        prod = Product(category="Zabawki", brand="Test", series="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

    # Record purchases in order (FIFO uses purchase_date)
    # First: price 7.0
    app_mod.record_purchase(pid, "M", 1, 7.0)
    # Second: price 5.0
    app_mod.record_purchase(pid, "M", 1, 5.0)
    # Third: price 6.0
    app_mod.record_purchase(pid, "M", 1, 6.0)

    # Consume 2 items - FIFO means oldest batches (7.0, then 5.0) depleted first
    consumed = app_mod.consume_stock(pid, "M", 2, sale_price=0)

    with app_mod.get_session() as db:
        qty = db.execute(
            text(
                "SELECT quantity FROM product_sizes WHERE product_id=:pid AND size=:size"
            ),
            {"pid": pid, "size": "M"},
        ).fetchone()[0]
        # Only get non-depleted batches
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
    # FIFO: oldest two batches (7.0, 5.0) depleted, newest (6.0) remains
    assert float(batches[0][0]) == 6.0
    assert batches[0][1] == 1
