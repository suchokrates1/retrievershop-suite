"""Weryfikacja importu faktury 2026/04/000182."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import Product, ProductSize, PurchaseBatch

app = create_app()
with app.app_context():
    with get_session() as db:
        batches = (
            db.query(PurchaseBatch)
            .filter_by(invoice_number="2026/04/000182")
            .order_by(PurchaseBatch.id)
            .all()
        )
        print(f"Batche z faktury 2026/04/000182: {len(batches)}")
        print(f"{'ID':>4} {'Prod':>4} {'Rozm':<12} {'Ilosc':>5} {'Cena':>8} {'Barcode':<15} {'Kategoria':<18} {'Seria':<22} {'Kolor':<15}")
        print("-" * 130)
        total_qty = 0
        total_value = 0
        for b in batches:
            p = db.query(Product).get(b.product_id)
            cat = p.category or p._name or "?"
            ser = p.series or "-"
            col = p.color or "-"
            total_qty += b.quantity
            total_value += float(b.price) * b.quantity
            print(
                f"{b.id:>4} {b.product_id:>4} {b.size:<12} {b.quantity:>5} "
                f"{float(b.price):>8.2f} {(b.barcode or '-'):<15} "
                f"{cat:<18} {ser:<22} {col:<15}"
            )
        print("-" * 130)
        print(f"Razem: {total_qty} szt., wartosc netto (zakup): {total_value:.2f} PLN")
