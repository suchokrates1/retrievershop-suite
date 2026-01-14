#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize, PurchaseBatch
from magazyn.db import get_session
from datetime import datetime

app = create_app()

with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 140)
        print("DOSTAWA z 2026-01-08 - szczegóły z purchase_batches")
        print("=" * 140)
        
        batches = session.query(PurchaseBatch).filter(
            PurchaseBatch.purchase_date >= datetime(2026, 1, 8),
            PurchaseBatch.purchase_date < datetime(2026, 1, 9)
        ).order_by(PurchaseBatch.id).all()
        
        print(f"\nZnaleziono {len(batches)} partii z dnia 2026-01-08\n")
        
        for batch in batches:
            product = session.query(Product).get(batch.product_id)
            print(f"[{batch.id:3d}] Product ID: {batch.product_id:3d} | Rozmiar: {batch.size:5s} | Ilość: {batch.quantity:3d} | "
                  f"EAN: {batch.barcode or 'BRAK':15s} | {product.name if product else 'BRAK PRODUKTU'}")
        
        print("\n" + "=" * 140)
        print("PORÓWNANIE Z FAKTURĄ:")
        print("=" * 140)
        
        invoice_items = [
            (1, "Pas samochodowy", "Uniwersalny", 6, "6976128181232"),
            (2, "Front Line Premium czarne", "XL", 4, "6971818794709"),
            (3, "Front Line Premium czarne", "S", 2, "6971818794679"),
            (4, "Front Line Premium brązowe", "XL", 4, "6971818795102"),
            (5, "Front Line Premium różowe", "S", 2, "6971818794822"),
            (6, "Front Line Premium czerwone", "M", 3, "6971818795133"),
            (7, "Front Line Premium czerwone", "S", 2, "6971818795126"),
            (8, "Front Line Premium pomarańczowe", "L", 5, "6971818794747"),
            (9, "Front Line Premium pomarańczowe", "S", 2, "6971818794723"),
            (10, "Tropical turkusowe", "M", 2, "6971818795188"),
            (11, "Front Line czarne", "XL", 3, "6970117170207"),
            (12, "Front Line czarne", "M", 2, "6970117170184"),
            (13, "Active czarny", "XL", 1, "6970117170641"),
            (14, "Active czarny", "L", 1, "6970117170634"),
            (15, "Active czarny", "M", 1, "6970117170627"),
            (16, "Outdoor czerwony", "2XL", 1, "6971273110694"),
            (17, "easy walk brązowe", "XL", 2, "6970117178500"),
            (18, "easy walk brązowe", "L", 2, "6970117178494"),
            (19, "easy walk brązowe", "M", 2, "6970117178487"),
        ]
        
        print("\nLp | Produkt (faktura)                    | Rozm | Ilość | EAN (faktura)   | Status")
        print("-" * 140)
        
        for lp, name, size, qty, ean in invoice_items:
            # Szukaj w bazie ProductSize po EAN
            product_size = session.query(ProductSize).filter_by(barcode=ean).first()
            if product_size:
                status = f"✓ ID {product_size.product_id}"
            else:
                status = "✗ BRAK W BAZIE"
            print(f"{lp:2d} | {name:38s} | {size:5s} | {qty:5d} | {ean:15s} | {status}")
