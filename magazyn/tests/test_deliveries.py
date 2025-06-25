import importlib
import sys
from sqlalchemy import text
from magazyn.models import Product, ProductSize


def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", ":memory:")
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
    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

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

    with app_mod.get_session() as db:
        batch = db.execute(
            text("SELECT quantity, price FROM purchase_batches WHERE product_id=:pid AND size=:size"),
            {"pid": pid, "size": "M"},
        ).fetchone()
        qty = db.execute(
            text("SELECT quantity FROM product_sizes WHERE product_id=:pid AND size=:size"),
            {"pid": pid, "size": "M"},
        ).fetchone()
    assert batch[0] == 3
    assert abs(batch[1] - 4.5) < 0.001
    assert qty[0] == 3


def test_consume_stock_cheapest(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Red")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=0))
        pid = prod.id

    app_mod.record_purchase(pid, "M", 2, 5.0)
    app_mod.record_purchase(pid, "M", 1, 4.0)
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
    assert batches[0][0] == 5.0
    assert batches[0][1] == 1
