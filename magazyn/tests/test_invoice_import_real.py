import importlib
from pathlib import Path
from sqlalchemy.sql import text
from magazyn.models import Product, ProductSize


def load_services():
    srv = importlib.import_module("magazyn.services")
    return importlib.reload(srv)


def test_import_invoice_file_real(app_mod):
    services = load_services()
    pdf_path = Path("magazyn/samples/sample_invoice.pdf")
    with pdf_path.open("rb") as f:
        f.filename = "sample_invoice.pdf"
        services.import_invoice_file(f)

    expected = [
        {
            "name": "Szelki dla psa Truelove Front Line Premium",
            "color": "różowe",
            "size": "XL",
            "qty": 5,
            "price": 134.33,
            "barcode": "6971818794853",
        },
        {
            "name": "Szelki dla psa Truelove Front Line Premium",
            "color": "niebieskie",
            "size": "XL",
            "qty": 5,
            "price": 134.33,
            "barcode": "6971818794808",
        },
        {
            "name": "Szelki dla psa Truelove Front Line Premium",
            "color": "niebieskie",
            "size": "L",
            "qty": 5,
            "price": 134.33,
            "barcode": "6971818794792",
        },
        {
            "name": "Profesjonalne szelki dla psa Truelove Front Line Premium",
            "color": "czerwone",
            "size": "XL",
            "qty": 5,
            "price": 134.33,
            "barcode": "6971818795157",
        },
        {
            "name": "Profesjonalne szelki dla psa Truelove Front Line Premium",
            "color": "czerwone",
            "size": "L",
            "qty": 10,
            "price": 134.33,
            "barcode": "6971818795140",
        },
        {
            "name": "Szelki dla psa Truelove Front Line Premium",
            "color": "fioletowe",
            "size": "XL",
            "qty": 5,
            "price": 134.33,
            "barcode": "6971818795058",
        },
        {
            "name": "Szelki z odpinanym przodem dla psa Truelove Front Line Premium",
            "color": "czarne",
            "size": "M",
            "qty": 5,
            "price": 134.33,
            "barcode": "6971818794686",
        },
        {
            "name": "Szelki z odpinanym przodem dla psa Truelove Front Line Premium",
            "color": "czarne",
            "size": "S",
            "qty": 6,
            "price": 134.33,
            "barcode": "6971818794679",
        },
        {
            "name": "Pas samochodowy dla psa Truelove Premium",
            "color": "srebrny",
            "size": "",
            "qty": 10,
            "price": 53.33,
            "barcode": "6976128181720",
        },
        {
            "name": "Szelki dla psa Truelove Front Line Premium",
            "color": "brązowe",
            "size": "XL",
            "qty": 5,
            "price": 134.33,
            "barcode": "6971818795102",
        },
    ]

    with app_mod.get_session() as db:
        count = db.execute(
            text("SELECT COUNT(*) FROM purchase_batches")
        ).scalar()
        assert count == len(expected)
        for item in expected:
            # Find product by barcode (most reliable)
            ps = (
                db.query(ProductSize)
                .filter(ProductSize.barcode == item["barcode"])
                .first()
            )
            assert ps is not None, f"ProductSize not found for barcode: {item['barcode']}"
            prod = ps.product
            assert prod is not None, f"Product not found for barcode: {item['barcode']}"
            
            # Verify color matches if provided in expected (some invoices may not have color)
            if item["color"] and prod.color:
                assert prod.color == item["color"], f"Color mismatch for {item['barcode']}: expected '{item['color']}', got '{prod.color}'"
            # Verify size matches
            assert ps.size == item["size"], f"Size mismatch for {item['barcode']}"
            assert ps.quantity == item["qty"]
            batch = db.execute(
                text(
                    "SELECT quantity, price FROM purchase_batches WHERE product_id=:pid AND size=:size"
                ),
                {"pid": prod.id, "size": item["size"]},
            ).fetchone()
            assert batch is not None
            assert batch[0] == item["qty"]
            assert abs(float(batch[1]) - item["price"]) < 0.001
