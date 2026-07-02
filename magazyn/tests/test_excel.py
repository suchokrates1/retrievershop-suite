import pandas as pd
from io import BytesIO
from sqlalchemy import text
from magazyn.models.products import Product, ProductSize


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
    """Konsumpcja z wielu dostaw wyceniana metoda sredniej wazonej (AVCO)."""
    from decimal import Decimal
    from magazyn.models.products import Sale

    with app_mod.get_session() as db:
        prod = Product(category="Zabawki", brand="Test", series="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

    # Trzy dostawy po 1 szt: 7.0 + 5.0 + 6.0 -> wartosc 18.00, 3 szt, srednia 6.
    app_mod.record_purchase(pid, "M", 1, 7.0)
    app_mod.record_purchase(pid, "M", 1, 5.0)
    app_mod.record_purchase(pid, "M", 1, 6.0)

    # Sprzedaz 2 szt po sredniej 6 -> koszt 12.00, zostaje 1 szt warta 6.00.
    consumed = app_mod.consume_stock(pid, "M", 2, sale_price=0)

    with app_mod.get_session() as db:
        ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
        sale = db.query(Sale).filter_by(product_id=pid).one()
    assert consumed == 2
    assert ps.quantity == 1  # 3 - 2 = 1
    assert ps.stock_value == Decimal("6.00")
    assert sale.purchase_cost == Decimal("12.00")
