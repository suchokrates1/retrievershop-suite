import pandas as pd
from io import BytesIO
from sqlalchemy.sql import text
from magazyn.models import Product, ProductSize


def test_import_invoice_creates_products(app_mod, tmp_path):
    df = pd.DataFrame([
        {
            "Nazwa": "ProdInv",
            "Kolor": "Blue",
            "Rozmiar": "M",
            "Ilość": 2,
            "Cena": 5.5,
            "Barcode": "inv-123",
        }
    ])
    file_path = tmp_path / "inv.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "inv.xlsx")}
        with app_mod.app.test_request_context(
            "/import_invoice",
            method="POST",
            data=data,
            content_type="multipart/form-data",
        ):
            from flask import session

            session["username"] = "x"
            app_mod.import_invoice.__wrapped__()

    with app_mod.get_session() as db:
        prod = db.query(Product).filter_by(name="ProdInv", color="Blue").first()
        assert prod is not None
        ps = db.query(ProductSize).filter_by(product_id=prod.id, size="M").first()
        assert ps.quantity == 2
        assert ps.barcode == "inv-123"
        batch = db.execute(
            text(
                "SELECT quantity, price FROM purchase_batches WHERE product_id=:pid AND size='M'"
            ),
            {"pid": prod.id},
        ).fetchone()
        assert batch[0] == 2
        assert abs(batch[1] - 5.5) < 0.001
