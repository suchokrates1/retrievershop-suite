#!/usr/bin/env python3
"""
Naprawa nieprawidłowych EAN-ów w bazie danych
"""

import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize
from magazyn.db import SessionLocal

app = create_app()

with app.app_context():
    db = SessionLocal()
    
    print("=" * 80)
    print("NAPRAWA NIEPRAWIDŁOWYCH EAN-ÓW")
    print("=" * 80)
    
    # Znalezione błędne EAN-y:
    # 1. Product ID 76, XL: 697432787885128 -> 6974327885128
    # 2. Product ID 77, XL: 697432787885227 -> 6974327885227
    
    fixes = [
        {
            "product_id": 76,
            "size": "XL",
            "old_ean": "697432787885128",
            "new_ean": "6974327885128"
        },
        {
            "product_id": 77,
            "size": "XL",
            "old_ean": "697432787885227",
            "new_ean": "6974327885227"
        }
    ]
    
    for fix in fixes:
        print(f"\nNaprawiam Product ID {fix['product_id']}, rozmiar {fix['size']}:")
        print(f"  Stary EAN: {fix['old_ean']} (15 cyfr)")
        print(f"  Nowy EAN:  {fix['new_ean']} (13 cyfr)")
        
        product_size = db.query(ProductSize).filter(
            ProductSize.product_id == fix['product_id'],
            ProductSize.size == fix['size']
        ).first()
        
        if not product_size:
            print(f"  ❌ BŁĄD: Nie znaleziono ProductSize dla Product ID {fix['product_id']}, rozmiar {fix['size']}")
            continue
        
        if product_size.barcode != fix['old_ean']:
            print(f"  ⚠️  UWAGA: Aktualny EAN w bazie ({product_size.barcode}) różni się od oczekiwanego ({fix['old_ean']})")
            print(f"  Pomijam...")
            continue
        
        # Aktualizacja
        product_size.barcode = fix['new_ean']
        db.commit()
        print(f"  ✅ EAN zaktualizowany pomyślnie")
    
    # Weryfikacja
    print("\n" + "=" * 80)
    print("WERYFIKACJA PO NAPRAWIE")
    print("=" * 80)
    
    for fix in fixes:
        product_size = db.query(ProductSize).filter(
            ProductSize.product_id == fix['product_id'],
            ProductSize.size == fix['size']
        ).first()
        
        if product_size:
            status = "✅" if product_size.barcode == fix['new_ean'] else "❌"
            print(f"\n{status} Product ID {fix['product_id']}, rozmiar {fix['size']}:")
            print(f"  Aktualny EAN: {product_size.barcode}")
            print(f"  Długość: {len(str(product_size.barcode))} cyfr")
    
    db.close()
    
    print("\n" + "=" * 80)
    print("NAPRAWA ZAKOŃCZONA")
    print("=" * 80)
