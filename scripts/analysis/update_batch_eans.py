#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aktualizuje EAN-y w purchase_batches z dostawy 2026-01-08
"""
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize, PurchaseBatch
from magazyn.db import get_session
from datetime import datetime

app = create_app()

with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 120)
        print("AKTUALIZACJA EAN-ÓW W PURCHASE_BATCHES")
        print("=" * 120)
        
        # Pobierz wszystkie batche z 2026-01-08 bez EAN
        batches = session.query(PurchaseBatch).filter(
            PurchaseBatch.purchase_date >= datetime(2026, 1, 8),
            PurchaseBatch.purchase_date < datetime(2026, 1, 9),
            (PurchaseBatch.barcode == None) | (PurchaseBatch.barcode == 'BRAK')
        ).order_by(PurchaseBatch.id).all()
        
        print(f"\nZnaleziono {len(batches)} partii bez EAN z dnia 2026-01-08\n")
        
        updated = 0
        not_found = 0
        
        for batch in batches:
            # Znajdź ProductSize dla tego produktu i rozmiaru
            product_size = session.query(ProductSize).filter_by(
                product_id=batch.product_id,
                size=batch.size
            ).first()
            
            product = session.query(Product).get(batch.product_id)
            product_name = product.name if product else "UNKNOWN"
            
            if product_size and product_size.barcode:
                old_ean = batch.barcode
                batch.barcode = product_size.barcode
                print(f"✓ [{batch.id:3d}] {product_name[:50]:50s} {batch.size:5s} | "
                      f"{old_ean or 'BRAK':15s} → {product_size.barcode}")
                updated += 1
            else:
                print(f"✗ [{batch.id:3d}] {product_name[:50]:50s} {batch.size:5s} | "
                      f"BRAK ProductSize z EAN!")
                not_found += 1
        
        # Commituj zmiany
        session.commit()
        
        print("\n" + "=" * 120)
        print(f"PODSUMOWANIE: Zaktualizowano {updated} partii, nie znaleziono EAN dla {not_found} partii")
        print("=" * 120)
        
        # Weryfikacja - pokaż wszystkie batche z tej dostawy
        print("\n" + "=" * 120)
        print("WERYFIKACJA - wszystkie partie z 2026-01-08:")
        print("=" * 120)
        
        all_batches = session.query(PurchaseBatch).filter(
            PurchaseBatch.purchase_date >= datetime(2026, 1, 8),
            PurchaseBatch.purchase_date < datetime(2026, 1, 9)
        ).order_by(PurchaseBatch.id).all()
        
        for batch in all_batches:
            product = session.query(Product).get(batch.product_id)
            status = "✓" if batch.barcode and batch.barcode != 'BRAK' else "✗"
            print(f"{status} [{batch.id:3d}] {product.name if product else 'UNKNOWN':50s} "
                  f"{batch.size:5s} | EAN: {batch.barcode or 'BRAK'}")
