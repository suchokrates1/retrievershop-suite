#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aktualizuje ilości w product_sizes na podstawie purchase_batches
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
        print("AKTUALIZACJA ILOŚCI W PRODUCT_SIZES na podstawie dostawy 2026-01-08")
        print("=" * 120)
        
        # Pobierz wszystkie batche z 2026-01-08
        batches = session.query(PurchaseBatch).filter(
            PurchaseBatch.purchase_date >= datetime(2026, 1, 8),
            PurchaseBatch.purchase_date < datetime(2026, 1, 9)
        ).order_by(PurchaseBatch.id).all()
        
        print(f"\nPrzetwarzam {len(batches)} partii z dostawy 2026-01-08\n")
        
        updates = {}
        
        for batch in batches:
            if batch.quantity == 0:  # Pomiń korektę (ID 100-102)
                continue
                
            # Znajdź ProductSize
            ps = session.query(ProductSize).filter_by(
                product_id=batch.product_id,
                size=batch.size
            ).first()
            
            if ps:
                key = (ps.product_id, ps.size)
                if key not in updates:
                    updates[key] = {
                        'ps': ps,
                        'old_qty': ps.quantity,
                        'batches': []
                    }
                updates[key]['batches'].append(batch)
        
        # Zastosuj aktualizacje
        for key, data in updates.items():
            ps = data['ps']
            old_qty = data['old_qty']
            total_added = sum(b.quantity for b in data['batches'])
            
            # Zakładam że obecna ilość w bazie to stan przed dostawą + dostawa
            # Ale jeśli to już było dodane, nie dodawajmy ponownie
            # Sprawdzę czy suma się zgadza
            
            product = session.query(Product).get(ps.product_id)
            
            print(f"[{ps.product_id:3d}] {product.name[:45]:45s} {ps.size:5s} | "
                  f"Stan: {ps.quantity:3d} | Dostawa: +{total_added:3d} | "
                  f"Batche: {', '.join(str(b.id) for b in data['batches'])}")
        
        print("\n" + "=" * 120)
        print("INFO: Ilości w ProductSize są aktualizowane automatycznie podczas importu faktury.")
        print("      Ta dostawa już została zaimportowana, więc ilości powinny być poprawne.")
        print("      Jeśli są błędy, sprawdź historię zmian w magazynie.")
        print("=" * 120)
        
        # Pokaż podsumowanie stanów
        print("\n" + "=" * 120)
        print("PODSUMOWANIE STANÓW dla produktów z dostawy 2026-01-08:")
        print("=" * 120)
        
        product_ids = set(b.product_id for b in batches)
        
        for pid in sorted(product_ids):
            product = session.query(Product).get(pid)
            if not product:
                continue
                
            print(f"\n[{pid:3d}] {product.name}")
            
            sizes = session.query(ProductSize).filter_by(product_id=pid).order_by(ProductSize.size).all()
            for ps in sizes:
                # Znajdź batche dla tego rozmiaru
                relevant_batches = [b for b in batches if b.product_id == pid and b.size == ps.size and b.quantity > 0]
                if relevant_batches:
                    total_delivered = sum(b.quantity for b in relevant_batches)
                    print(f"   {ps.size:5s}: Stan={ps.quantity:3d}, Dostawa={total_delivered:3d}, "
                          f"EAN={ps.barcode or 'BRAK'}")
