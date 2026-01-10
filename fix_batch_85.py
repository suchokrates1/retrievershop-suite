#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import PurchaseBatch
from magazyn.db import get_session

app = create_app()

with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 100)
        print("AKTUALIZACJA purchase_batches dla Front Line Premium różowe")
        print("=" * 100)
        
        # Znajdź batch ID 85 (powinien mieć product_id=41, size=XS)
        batch = session.query(PurchaseBatch).get(85)
        
        if batch:
            print(f"\nBatch ID 85:")
            print(f"  Product ID: {batch.product_id}")
            print(f"  Przed: Rozmiar = {batch.size}, Ilość = {batch.quantity}, EAN = {batch.barcode}")
            
            batch.size = 'S'  # Zmień z XS na S
            
            print(f"  Po:    Rozmiar = {batch.size}, Ilość = {batch.quantity}, EAN = {batch.barcode}")
            
            session.commit()
            print("\n✓ Zaktualizowano pomyślnie!")
        else:
            print("\n✗ Batch ID 85 nie znaleziony!")
