import importlib
import sys
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
    import magazyn.db as db_mod
    from sqlalchemy.orm import sessionmaker
    db_mod.SessionLocal = sessionmaker(
        bind=db_mod.engine, autoflush=False, expire_on_commit=False
    )
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    app_mod.init_db()
    return app_mod


def login(client):
    with client.session_transaction() as sess:
        sess["username"] = "tester"


def test_product_crud_and_barcode_scan(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    login(client)

    # add product
    data_add = {
        "name": "Prod",
        "color": "Czerwony",
        "quantity_M": "2",
        "barcode_M": "111",
    }
    resp = client.post("/add_item", data=data_add)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        prod = db.query(Product).filter_by(name="Prod").first()
        assert prod is not None
        prod_id = prod.id
        ps = db.query(ProductSize).filter_by(product_id=prod_id, size="M").first()
        assert ps.quantity == 2
        assert ps.barcode == "111"

    # edit product
    data_edit = {
        "name": "Prod2",
        "color": "Zielony",
        "quantity_M": "5",
        "barcode_M": "111",
    }
    resp = client.post(f"/edit_item/{prod_id}", data=data_edit)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        prod = db.get(Product, prod_id)
        assert prod.name == "Prod2"
        assert prod.color == "Zielony"
        ps = db.query(ProductSize).filter_by(product_id=prod_id, size="M").first()
        assert ps.quantity == 5

    # barcode scan
    resp = client.post("/barcode_scan", json={"barcode": "111"})
    assert resp.status_code == 200
    assert resp.get_json() == {"name": "Prod2", "color": "Zielony", "size": "M"}

    # delete product
    resp = client.post(f"/delete_item/{prod_id}")
    assert resp.status_code == 302
    with app_mod.get_session() as db:
        assert db.get(Product, prod_id) is None
        assert not db.query(ProductSize).filter_by(product_id=prod_id).first()


def test_items_forms_include_csrf_token(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    login(client)

    with app_mod.get_session() as db:
        prod = Product(name="P", color="C")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=1))

    resp = client.get("/items")
    html = resp.get_data(as_text=True)
    from flask import session as flask_session
    with client.session_transaction() as sess:
        with app_mod.app.test_request_context():
            for k, v in sess.items():
                flask_session[k] = v
            token = app_mod.app.jinja_env.globals["csrf_token"]()
    assert html.count(token) >= 7


def test_edit_item_get_shows_product_details(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    login(client)

    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Blue")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=4, barcode="123"))
        pid = prod.id

    resp = client.get(f"/edit_item/{pid}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Prod" in html
    assert "Blue" in html
