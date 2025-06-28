import pandas as pd
from pathlib import Path
from sqlalchemy.sql import text
from magazyn.models import Product, ProductSize


def test_import_invoice_creates_products(app_mod, client, login, tmp_path):
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
        resp = client.post("/import_invoice", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert "ProdInv" in resp.get_data(as_text=True)

    confirm = {
        "name_0": "ProdInv",
        "color_0": "Blue",
        "size_0": "M",
        "quantity_0": "2",
        "price_0": "5.5",
        "barcode_0": "inv-123",
        "accept_0": "y",
    }
    resp = client.post("/confirm_invoice", data=confirm)
    assert resp.status_code == 302

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


def test_import_invoice_with_spaces(app_mod, client, login, tmp_path):
    df = pd.DataFrame([
        {
            "Nazwa": "ProdSpace",
            "Kolor": "Green",
            "Rozmiar": "L",
            "Ilość": "1 234",
            "Cena": "2 345,67",
            "Barcode": "sp-456",
        }
    ])
    file_path = tmp_path / "inv2.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "inv.xlsx")}
        resp = client.post("/import_invoice", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200

    confirm = {
        "name_0": "ProdSpace",
        "color_0": "Green",
        "size_0": "L",
        "quantity_0": "1 234",
        "price_0": "2 345,67",
        "barcode_0": "sp-456",
        "accept_0": "y",
    }
    resp = client.post("/confirm_invoice", data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        prod = db.query(Product).filter_by(name="ProdSpace", color="Green").first()
        assert prod is not None
        ps = db.query(ProductSize).filter_by(product_id=prod.id, size="L").first()
        assert ps.quantity == 1234
        batch = db.execute(
            text(
                "SELECT price FROM purchase_batches WHERE product_id=:pid AND size='L'"
            ),
            {"pid": prod.id},
        ).fetchone()
        assert abs(batch[0] - 2345.67) < 0.001


def test_import_invoice_pdf(app_mod, client, login):
    pdf_path = Path('magazyn/tests/data/sample_invoice.pdf')
    with pdf_path.open('rb') as f:
        data = {'file': (f, 'inv.pdf')}
        resp = client.post('/import_invoice', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200

    confirm = {"name_0": "Rain Coat", "color_0": "", "size_0": "XL", "quantity_0": "2", "price_0": "0", "barcode_0": "", "accept_0": "y"}
    resp = client.post('/confirm_invoice', data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        prod = db.query(Product).filter_by(name='Rain Coat').first()
        assert prod is not None
        ps = db.query(ProductSize).filter_by(product_id=prod.id, size='XL').first()
        assert ps.quantity == 2


def test_import_invoice_pdf_skips_invalid_size(app_mod, client, login):
    pdf_path = Path('magazyn/tests/data/sample_invalid.pdf')
    with pdf_path.open('rb') as f:
        data = {'file': (f, 'inv.pdf')}
        resp = client.post('/import_invoice', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200

    confirm = {"accept_0": "y"}
    resp = client.post('/confirm_invoice', data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        assert db.query(Product).filter_by(name='Test Product').first() is None
        prod = db.query(Product).filter_by(name='Another').first()
        assert prod is not None
        ps = db.query(ProductSize).filter_by(product_id=prod.id, size='M').first()
        assert ps.quantity == 1


def test_confirm_invoice_updates_existing(app_mod, client, login, tmp_path):
    with app_mod.get_session() as db:
        prod = Product(name='Existing', color='Red')
        db.add(prod)
        db.flush()
        ps = ProductSize(product_id=prod.id, size='M', quantity=1)
        db.add(ps)
        db.flush()
        ps_id = ps.id

    df = pd.DataFrame([
        {'Nazwa': 'Other', 'Kolor': 'Blue', 'Rozmiar': 'L', 'Ilość': 2, 'Cena': 3.0, 'Barcode': ''}
    ])
    file_path = tmp_path / 'inv.xlsx'
    df.to_excel(file_path, index=False)

    with open(file_path, 'rb') as f:
        data = {'file': (f, 'inv.xlsx')}
        resp = client.post('/import_invoice', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200

    confirm = {
        'name_0': 'Other',
        'color_0': 'Blue',
        'size_0': 'L',
        'quantity_0': '2',
        'price_0': '3.0',
        'barcode_0': '',
        'ps_id_0': str(ps_id),
        'accept_0': 'y',
    }
    resp = client.post('/confirm_invoice', data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        assert db.query(Product).filter_by(name='Other').first() is None
        ps = db.query(ProductSize).filter_by(id=ps_id).first()
        assert ps.quantity == 3
        batch = db.execute(
            text(
                "SELECT quantity FROM purchase_batches WHERE product_id=:pid AND size='M'"
            ),
            {'pid': prod.id},
        ).fetchone()
        assert batch[0] == 2
