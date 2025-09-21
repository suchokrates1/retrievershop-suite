from magazyn.constants import ALL_SIZES
from magazyn.domain.products import _to_int, create_product, get_product_details
from magazyn.models import Product, ProductSize


def test_add_and_edit_item(app_mod, client, login):
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
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod_id, size="M")
            .first()
        )
        assert ps.quantity == 2
        assert ps.barcode == "111"

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
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod_id, size="M")
            .first()
        )
        assert ps.quantity == 5


def test_barcode_scan(app_mod, client, login):
    with app_mod.get_session() as db:
        prod = Product(name="Prod2", color="Zielony")
        db.add(prod)
        db.flush()
        db.add(
            ProductSize(
                product_id=prod.id, size="M", quantity=1, barcode="111"
            )
        )

    resp = client.post("/barcode_scan", json={"barcode": "111"})
    assert resp.status_code == 200
    assert resp.get_json() == {
        "name": "Prod2",
        "color": "Zielony",
        "size": "M",
    }


def test_barcode_scan_invalid(app_mod, client, login):
    resp = client.post("/barcode_scan", json={"barcode": "999"})
    assert resp.status_code == 400
    with client.session_transaction() as sess:
        msgs = sess.get("_flashes")
    assert any("Nie znaleziono" in m for _, m in msgs)


def test_barcode_scan_empty(app_mod, client, login):
    resp = client.post("/barcode_scan", json={"barcode": ""})
    assert resp.status_code == 400


def test_delete_item(app_mod, client, login):
    with app_mod.get_session() as db:
        prod = Product(name="Del", color="Green")
        db.add(prod)
        db.flush()
        db.add(ProductSize(product_id=prod.id, size="M", quantity=2))
        prod_id = prod.id

    resp = client.post(f"/delete_item/{prod_id}")
    assert resp.status_code == 302
    with app_mod.get_session() as db:
        assert db.get(Product, prod_id) is None
        assert not db.query(ProductSize).filter_by(product_id=prod_id).first()


def test_items_forms_include_csrf_token(app_mod, client, login):

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


def test_edit_item_get_shows_product_details(app_mod, client, login):

    with app_mod.get_session() as db:
        prod = Product(name="Prod", color="Blue")
        db.add(prod)
        db.flush()
        db.add(
            ProductSize(
                product_id=prod.id, size="M", quantity=4, barcode="123"
            )
        )
        pid = prod.id

    resp = client.get(f"/edit_item/{pid}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Prod" in html
    assert "Blue" in html


def test_items_page_displays_barcodes(app_mod, client, login):

    with app_mod.get_session() as db:
        prod = Product(name="P", color="C")
        db.add(prod)
        db.flush()
        db.add(
            ProductSize(
                product_id=prod.id, size="M", quantity=2, barcode="321"
            )
        )

    resp = client.get("/items")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "321" not in html


def test_scan_barcode_page_contains_csrf(app_mod, client, login):

    resp = client.get("/scan_barcode")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    from flask import session as flask_session

    with client.session_transaction() as sess:
        with app_mod.app.test_request_context():
            for k, v in sess.items():
                flask_session[k] = v
            token = app_mod.app.jinja_env.globals["csrf_token"]()
    assert token in html


def test_edit_nonexistent_product_returns_404(app_mod, client, login):
    resp = client.get("/edit_item/999")
    assert resp.status_code == 404


def test_delete_nonexistent_product_returns_404(app_mod, client, login):
    resp = client.post("/delete_item/999")
    assert resp.status_code == 404


def test_add_item_rejects_negative_quantity(app_mod, client, login):

    data = {
        "name": "NegProd",
        "color": "Czerwony",
        "quantity_M": "-1",
    }
    resp = client.post("/add_item", data=data)
    # Form should re-render when validation fails
    assert resp.status_code == 200

    with app_mod.get_session() as db:
        assert db.query(Product).filter_by(name="NegProd").first() is None


def test_domain_create_product_persists_sizes(app_mod):
    quantities = {size: idx for idx, size in enumerate(ALL_SIZES, start=1)}
    barcodes = {size: f"code-{size}" for size in ALL_SIZES}

    product = create_product("DomainProd", "Niebieski", quantities, barcodes)

    assert product.id is not None

    details, sizes = get_product_details(product.id)
    assert details == {"id": product.id, "name": "DomainProd", "color": "Niebieski"}
    for size in ALL_SIZES:
        assert sizes[size]["quantity"] == quantities[size]
        assert sizes[size]["barcode"] == barcodes[size]


def test_to_int_handles_strings_with_spaces():
    assert _to_int("1 234") == 1234
    assert _to_int("12,5") == 125
    assert _to_int(None) == 0
