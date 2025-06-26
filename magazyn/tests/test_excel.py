import importlib
import pandas as pd
import sys
from io import BytesIO
from sqlalchemy import text
from magazyn.models import Product, ProductSize


def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", ":memory:")
    import werkzeug
    monkeypatch.setattr(werkzeug, "__version__", "0", raising=False)
    init = importlib.import_module("magazyn.__init__")
    importlib.reload(init)
    monkeypatch.setitem(sys.modules, "__init__", init)
    pa = importlib.import_module("magazyn.print_agent")
    monkeypatch.setitem(sys.modules, "print_agent", pa)
    monkeypatch.setattr(pa, "start_agent_thread", lambda: None)
    monkeypatch.setattr(pa, "ensure_db_init", lambda: None)
    monkeypatch.setattr(pa, "validate_env", lambda: None)
    import magazyn.app as app_mod
    importlib.reload(app_mod)
    app_mod.reset_db()
    return app_mod


def test_export_products_includes_barcode(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=5, barcode="123"))

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "x"

    resp = client.get("/export_products")

    df = pd.read_excel(BytesIO(resp.data))
    assert "Barcode" in df.columns
    assert str(df.loc[0, "Barcode"]) == "123"


def test_import_products_reads_barcode(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    df = pd.DataFrame([
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
    ])
    file_path = tmp_path / "import.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "import.xlsx")}
        with app_mod.app.test_request_context(
            "/import_products", method="POST", data=data, content_type="multipart/form-data"
        ):
            from flask import session
            session["username"] = "x"
            app_mod.import_products.__wrapped__()

    with app_mod.get_session() as db:
        row = db.execute(
            text(
                "SELECT ps.barcode FROM product_sizes ps JOIN products p ON ps.product_id = p.id WHERE p.name=:name AND p.color=:color AND ps.size='M'"
            ),
            {"name": "Prod", "color": "Red"},
        ).fetchone()
        assert row[0] == "999"


def test_consume_stock_multiple_batches(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

    # record purchases in non-sorted order by price
    app_mod.record_purchase(pid, "M", 1, 7.0)
    app_mod.record_purchase(pid, "M", 1, 5.0)
    app_mod.record_purchase(pid, "M", 1, 6.0)

    consumed = app_mod.consume_stock(pid, "M", 2)

    with app_mod.get_session() as db:
        qty = db.execute(
            text("SELECT quantity FROM product_sizes WHERE product_id=:pid AND size=:size"),
            {"pid": pid, "size": "M"},
        ).fetchone()[0]
        batches = db.execute(
            text("SELECT price, quantity FROM purchase_batches WHERE product_id=:pid AND size=:size ORDER BY price"),
            {"pid": pid, "size": "M"},
        ).fetchall()
    assert consumed == 2
    assert qty == 1
    assert len(batches) == 1
    assert batches[0][0] == 7.0
    assert batches[0][1] == 1
