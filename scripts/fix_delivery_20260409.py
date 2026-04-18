"""Naprawa blednych batchow z pierwszego importu faktury 2026/04/000182.

Pierwszy import uzywal barcodes produktowych zamiast wariantowych,
co spowodowalo przypisanie niektorych pozycji do zlych rozmiarow.
Drugi import poprawnie utworzyl brakujace batche z wariantowymi barcodes.
Ten skrypt usuwa 4 bledne batche i koryguje stan magazynowy.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import ProductSize, PurchaseBatch

# Bledne batche do usuniecia (ID: opis bledu)
BAD_BATCHES = {
    12: "product=11 XL qty=3, powinno byc L (poprawiony przez batch 27)",
    16: "product=14 XL qty=3, powinno byc L (poprawiony przez batch 30)",
    17: "product=14 XL qty=5, powinno byc M (poprawiony przez batch 31)",
    21: "product=17 M qty=1, bledny produkt (poprawiony przez batch 32)",
}

app = create_app()
with app.app_context():
    with get_session() as db:
        for batch_id, reason in BAD_BATCHES.items():
            batch = db.query(PurchaseBatch).get(batch_id)
            if not batch:
                print(f"  Batch {batch_id} nie istnieje - pomijam")
                continue
            if batch.invoice_number != "2026/04/000182":
                print(f"  UWAGA: Batch {batch_id} ma inna fakture ({batch.invoice_number}) - pomijam!")
                continue
            
            # Skoryguj stan magazynowy
            ps = (
                db.query(ProductSize)
                .filter_by(product_id=batch.product_id, size=batch.size)
                .first()
            )
            if ps:
                old_qty = ps.quantity
                ps.quantity = max(0, ps.quantity - batch.quantity)
                print(
                    f"  Batch {batch_id}: produkt={batch.product_id} "
                    f"rozmiar={batch.size} qty={batch.quantity} - USUWAM "
                    f"(stan: {old_qty} -> {ps.quantity}) [{reason}]"
                )
            
            db.delete(batch)
        
        print("\nGotowe. Bledne batche usuniete i stany magazynowe skorygowane.")
