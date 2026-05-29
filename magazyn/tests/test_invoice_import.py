import pandas as pd
from pathlib import Path
from sqlalchemy.sql import text
from magazyn.domain.invoice_import import (
    _extract_invoice_metadata,
    _parse_ksef_text,
    import_invoice_rows,
    parse_product_name_to_fields,
)
from magazyn.models.products import Product, ProductSize, PurchaseBatch


def test_import_invoice_creates_products(app_mod, client, login, tmp_path):
    df = pd.DataFrame(
        [
            {
                "Nazwa": "ProdInv",
                "Kolor": "Blue",
                "Rozmiar": "M",
                "Ilość": 2,
                "Cena": 5.5,
                "Barcode": "1234567890128",
            }
        ]
    )
    file_path = tmp_path / "inv.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "inv.xlsx")}
        resp = client.post(
            "/import_invoice", data=data, content_type="multipart/form-data"
        )
    assert resp.status_code == 200
    assert "ProdInv" in resp.get_data(as_text=True)

    confirm = {
        "name_0": "ProdInv",
        "color_0": "Blue",
        "size_0": "M",
        "quantity_0": "2",
        "price_0": "5.5",
        "barcode_0": "1234567890128",
        "accept_0": "y",
    }
    resp = client.post("/confirm_invoice", data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        # Use _name column for SQL query since name is a hybrid_property
        prod = (
            db.query(Product).filter(Product._name == "ProdInv", Product.color == "Blue").first()
        )
        assert prod is not None
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod.id, size="M")
            .first()
        )
        assert ps.quantity == 2
        assert ps.barcode == "1234567890128"
        batch = db.execute(
            text(
                "SELECT quantity, price FROM purchase_batches WHERE product_id=:pid AND size='M'"
            ),
            {"pid": prod.id},
        ).fetchone()
        assert batch[0] == 2
        assert abs(float(batch[1]) - 5.5) < 0.001


def test_import_invoice_with_spaces(app_mod, client, login, tmp_path):
    df = pd.DataFrame(
        [
            {
                "Nazwa": "ProdSpace",
                "Kolor": "Green",
                "Rozmiar": "L",
                "Ilość": "1 234",
                "Cena": "2 345,67",
                "Barcode": "4567890123456",
            }
        ]
    )
    file_path = tmp_path / "inv2.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "inv.xlsx")}
        resp = client.post(
            "/import_invoice", data=data, content_type="multipart/form-data"
        )
    assert resp.status_code == 200

    confirm = {
        "name_0": "ProdSpace",
        "color_0": "Green",
        "size_0": "L",
        "quantity_0": "1 234",
        "price_0": "2 345,67",
        "barcode_0": "4567890123456",
        "accept_0": "y",
    }
    resp = client.post("/confirm_invoice", data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        prod = (
            db.query(Product)
            .filter(Product._name == "ProdSpace", Product.color == "Green")
            .first()
        )
        assert prod is not None
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod.id, size="L")
            .first()
        )
        assert ps.quantity == 1234
        batch = db.execute(
            text(
                "SELECT price FROM purchase_batches WHERE product_id=:pid AND size='L'"
            ),
            {"pid": prod.id},
        ).fetchone()
        assert abs(float(batch[0]) - 2345.67) < 0.001


def test_import_invoice_pdf(app_mod, client, login):
    pdf_path = Path("magazyn/tests/data/sample_invoice.pdf")
    with pdf_path.open("rb") as f:
        data = {"file": (f, "inv.pdf")}
        resp = client.post(
            "/import_invoice", data=data, content_type="multipart/form-data"
        )
    assert resp.status_code == 200

    confirm = {
        "name_0": "Rain Coat",
        "color_0": "",
        "size_0": "XL",
        "quantity_0": "2",
        "price_0": "0",
        "barcode_0": "",
        "accept_0": "y",
    }
    resp = client.post("/confirm_invoice", data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        prod = db.query(Product).filter(Product._name == "Rain Coat").first()
        assert prod is not None
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod.id, size="XL")
            .first()
        )
        assert ps.quantity == 2


def test_import_invoice_pdf_skips_invalid_size(app_mod, client, login):
    pdf_path = Path("magazyn/tests/data/sample_invalid.pdf")
    with pdf_path.open("rb") as f:
        data = {"file": (f, "inv.pdf")}
        resp = client.post(
            "/import_invoice", data=data, content_type="multipart/form-data"
        )
    assert resp.status_code == 200

    confirm = {"accept_0": "y"}
    resp = client.post("/confirm_invoice", data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        assert db.query(Product).filter(Product._name == "Test Product").first() is None
        prod = db.query(Product).filter(Product._name == "Another").first()
        assert prod is not None
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod.id, size="M")
            .first()
        )
        assert ps.quantity == 1


def test_parse_ksef_invoice_text_maps_gtin_and_new_variants():
    text = """
Numer faktury
FS 2026/05/000415Faktura podstawowa
Sprzedawca
NIP: 5992999304
Nazwa: TIP-TOP Agnieszka Pawlicka
Pozycje
Faktura wystawiona w cenach brutto w walucie PLN
Lp. Nazwa towaru lub usługi Cena jedn. brutto Ilość Miara Rabat Stawka
podatkuWartość sprzedaży
brutto
1 Smycz dla psa z amortyzatorem Truelove
Adventure czarny> L74.25 3 szt 7.42 23% 200.49
2 Kapok dla psa Truelove Dive liliowy> M (69-81
cm)194.25 1 szt 29.14 23% 165.11
3 Kamizelka chłodząca dla psa Truelove żółta>
XXL149.25 1 szt 14.92 23% 134.33
4 Linka treningowa wodoodporna dla psa Hexa
(13mm, 5m) pomarańczowa69.75 1 szt 6.97 23% 62.78
Lp. GTIN Indeks
1 6971818794228 TL-SM-advent-L-CZA
2 6976128188422 TL-KAP-DIVE-M-LIL
3 6970117172058 TL-KA-CHL-XXL-ZOL
4 5905544764607 SV-SM-hex13-5m-POM-DPR
"""

    df = _parse_ksef_text(text)
    invoice_number, supplier = _extract_invoice_metadata(text)

    assert invoice_number == "FS 2026/05/000415"
    assert supplier == "TIP-TOP Agnieszka Pawlicka"
    assert len(df) == 4
    assert df.iloc[0].to_dict() | {"Cena": round(df.iloc[0]["Cena"], 2)} == {
        "Nazwa": "Smycz dla psa z amortyzatorem Truelove Adventure",
        "Kolor": "czarny",
        "Rozmiar": "L",
        "Ilość": 3,
        "Cena": 66.83,
        "Barcode": "6971818794228",
        "SKU": "TL-SM-advent-L-CZA",
    }
    assert df.iloc[2]["Rozmiar"] == "2XL"
    assert df.iloc[2]["Kolor"] == "żółta"
    assert df.iloc[3]["Rozmiar"] == "Uniwersalny"
    assert df.iloc[3]["Kolor"] == "pomarańczowa"
    assert parse_product_name_to_fields(df.iloc[1]["Nazwa"]) == (
        "Kapok",
        "Truelove",
        "Dive",
    )
    assert parse_product_name_to_fields(df.iloc[2]["Nazwa"]) == (
        "Kamizelka",
        "Truelove",
        "Chłodząca",
    )
    assert parse_product_name_to_fields(df.iloc[3]["Nazwa"]) == (
        "Linka",
        "Hexa",
        "Treningowa wodoodporna 13mm 5m",
    )


def test_confirm_invoice_updates_existing(app_mod, client, login, tmp_path):
    with app_mod.get_session() as db:
        prod = Product(name="Existing", color="Red")
        db.add(prod)
        db.flush()
        ps = ProductSize(product_id=prod.id, size="M", quantity=1)
        db.add(ps)
        db.flush()
        ps_id = ps.id

    df = pd.DataFrame(
        [
            {
                "Nazwa": "Other",
                "Kolor": "Blue",
                "Rozmiar": "L",
                "Ilość": 2,
                "Cena": 3.0,
                "Barcode": "",
            }
        ]
    )
    file_path = tmp_path / "inv.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "inv.xlsx")}
        resp = client.post(
            "/import_invoice", data=data, content_type="multipart/form-data"
        )
    assert resp.status_code == 200

    confirm = {
        "name_0": "Other",
        "color_0": "Blue",
        "size_0": "L",
        "quantity_0": "2",
        "price_0": "3.0",
        "barcode_0": "",
        "ps_id_0": str(ps_id),
        "accept_0": "y",
    }
    resp = client.post("/confirm_invoice", data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        assert db.query(Product).filter(Product._name == "Other").first() is None
        ps = db.query(ProductSize).filter_by(id=ps_id).first()
        assert ps.quantity == 3
        batch = db.execute(
            text(
                "SELECT quantity FROM purchase_batches WHERE product_id=:pid AND size='M'"
            ),
            {"pid": prod.id},
        ).fetchone()
        assert batch[0] == 2


def test_import_invoice_alias_matches_existing(app_mod, client, login, tmp_path):
    with app_mod.get_session() as db:
        # Create product with new structure (category, brand, series)
        prod = Product(category="Szelki", brand="Truelove", series="Tropical", color="turkusowe")
        db.add(prod)
        db.flush()
        ps = ProductSize(product_id=prod.id, size="L", quantity=1)
        db.add(ps)
        db.flush()

    df = pd.DataFrame(
        [
            {
                "Nazwa": "Szelki dla psa Truelove Front Line Premium Tropical",
                "Kolor": "turkusowe",
                "Rozmiar": "L",
                "Ilość": 2,
                "Cena": 4.0,
                "Barcode": "",
            }
        ]
    )
    file_path = tmp_path / "alias.xlsx"
    df.to_excel(file_path, index=False)

    with open(file_path, "rb") as f:
        data = {"file": (f, "alias.xlsx")}
        resp = client.post(
            "/import_invoice", data=data, content_type="multipart/form-data"
        )
    assert resp.status_code == 200

    confirm = {
        "name_0": "Szelki dla psa Truelove Front Line Premium Tropical",
        "color_0": "turkusowe",
        "size_0": "L",
        "quantity_0": "2",
        "price_0": "4.0",
        "barcode_0": "",
        "accept_0": "y",
    }
    resp = client.post("/confirm_invoice", data=confirm)
    assert resp.status_code == 302

    with app_mod.get_session() as db:
        # Search by structured fields (category, series, color)
        prod = (
            db.query(Product)
            .filter_by(category="Szelki", series="Tropical", color="turkusowe")
            .first()
        )
        assert prod is not None
        # Verify there's no product with "Front Line Premium Tropical" series
        assert (
            db.query(Product)
            .filter_by(series="Front Line Premium Tropical")
            .first()
            is None
        )
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=prod.id, size="L")
            .first()
        )
        assert ps.quantity == 3


def test_import_invoice_rows_updates_existing_by_barcode(app_mod):
    with app_mod.get_session() as db:
        product = Product(name="Existing", color="Red")
        db.add(product)
        db.flush()
        db.add(
            ProductSize(
                product_id=product.id, size="M", quantity=1, barcode="7890123456789"
            )
        )

    import_invoice_rows(
        [
            {
                "Nazwa": "Existing",
                "Kolor": "Red",
                "Rozmiar": "M",
                "Ilość": 2,
                "Cena": "5.50",
                "Barcode": "7890123456789",
            }
        ]
    )

    with app_mod.get_session() as db:
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=product.id, size="M")
            .first()
        )
        assert ps.quantity == 3
        batch = (
            db.query(PurchaseBatch)
            .filter_by(product_id=product.id, size="M")
            .one()
        )
        assert float(batch.price) == 5.5


def test_import_invoice_rows_creates_new_product(app_mod):
    import_invoice_rows(
        [
            {
                "Nazwa": "NewProd",
                "Kolor": "Blue",
                "Rozmiar": "L",
                "Ilość": 4,
                "Cena": "7.25",
                "Barcode": "",
            }
        ]
    )

    with app_mod.get_session() as db:
        product = (
            db.query(Product)
            .filter(Product._name == "NewProd", Product.color == "Blue")
            .one()
        )
        ps = (
            db.query(ProductSize)
            .filter_by(product_id=product.id, size="L")
            .one()
        )
        assert ps.quantity == 4
        assert ps.barcode is None
