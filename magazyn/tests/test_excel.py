import importlib
import pandas as pd
import sys


def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
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
    app_mod.init_db()
    return app_mod


def test_export_products_includes_barcode(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    with app_mod.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (name, color, barcode) VALUES (?, ?, ?)",
            ("Prod", "Red", "123"),
        )
        pid = cur.lastrowid
        cur.execute(
            "INSERT INTO product_sizes (product_id, size, quantity) VALUES (?, ?, ?)",
            (pid, "M", 5),
        )
        conn.commit()

    with app_mod.app.test_request_context():
        from flask import session
        session['username'] = 'x'
        app_mod.export_products.__wrapped__()

    df = pd.read_excel("/tmp/products_export.xlsx")
    assert "Barcode" in df.columns
    assert str(df.loc[0, "Barcode"]) == "123"


def test_import_products_reads_barcode(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    df = pd.DataFrame([
        {
            "Nazwa": "Prod",
            "Kolor": "Red",
            "Barcode": "999",
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

    with app_mod.get_db_connection() as conn:
        row = conn.execute(
            "SELECT barcode FROM products WHERE name=? AND color=?",
            ("Prod", "Red"),
        ).fetchone()
        assert row["barcode"] == "999"


def test_consume_stock_multiple_batches(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    with app_mod.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO products (name, color) VALUES (?, ?)", ("Prod", "Red"))
        pid = cur.lastrowid
        cur.execute(
            "INSERT INTO product_sizes (product_id, size, quantity) VALUES (?, ?, ?)",
            (pid, "M", 0),
        )
        conn.commit()

    # record purchases in non-sorted order by price
    app_mod.record_purchase(pid, "M", 1, 7.0)
    app_mod.record_purchase(pid, "M", 1, 5.0)
    app_mod.record_purchase(pid, "M", 1, 6.0)

    consumed = app_mod.consume_stock(pid, "M", 2)

    with app_mod.get_db_connection() as conn:
        qty = conn.execute(
            "SELECT quantity FROM product_sizes WHERE product_id=? AND size=?",
            (pid, "M"),
        ).fetchone()["quantity"]
        batches = conn.execute(
            "SELECT price, quantity FROM purchase_batches WHERE product_id=? AND size=? ORDER BY price",
            (pid, "M"),
        ).fetchall()
    assert consumed == 2
    assert qty == 1
    assert len(batches) == 1
    assert batches[0]["price"] == 7.0
    assert batches[0]["quantity"] == 1
