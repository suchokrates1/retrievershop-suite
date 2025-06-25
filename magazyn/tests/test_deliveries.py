import importlib
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


def test_record_delivery(tmp_path, monkeypatch):
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

    data = {
        "product_id": str(pid),
        "size": "M",
        "quantity": "3",
        "price": "4.5",
    }
    with app_mod.app.test_request_context("/deliveries", method="POST", data=data):
        from flask import session
        session["username"] = "x"
        app_mod.add_delivery.__wrapped__()

    with app_mod.get_db_connection() as conn:
        batch = conn.execute(
            "SELECT quantity, price FROM purchase_batches WHERE product_id=? AND size=?",
            (pid, "M"),
        ).fetchone()
        qty = conn.execute(
            "SELECT quantity FROM product_sizes WHERE product_id=? AND size=?",
            (pid, "M"),
        ).fetchone()
    assert batch["quantity"] == 3
    assert abs(batch["price"] - 4.5) < 0.001
    assert qty["quantity"] == 3


def test_consume_stock_cheapest(tmp_path, monkeypatch):
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

    app_mod.record_purchase(pid, "M", 2, 5.0)
    app_mod.record_purchase(pid, "M", 1, 4.0)
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
    assert batches[0]["price"] == 5.0
    assert batches[0]["quantity"] == 1
