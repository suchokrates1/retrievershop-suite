#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sprawdza brakujące EAN-y i szuka odpowiednich produktów w bazie
"""

import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize
from magazyn.db import get_session

app = create_app()

# Brakujące EAN-y z faktury
missing_eans = {
    '6971818794709': 'Szelki Front Line Premium czarne XL',
    '6971818794679': 'Szelki Front Line Premium czarne S',
    '6971818795126': 'Szelki Front Line Premium czerwone S',
    '6970117170184': 'Szelki Front Line czarne M'
}

with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 120)
        print("BRAKUJĄCE EAN-Y - ANALIZA PRODUKTÓW")
        print("=" * 120)
    
with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 120)
        print("BRAKUJĄCE EAN-Y - ANALIZA PRODUKTÓW")
        print("=" * 120)
        
        for ean, description in missing_eans.items():
            print(f"\n🔍 Szukam: {description}")
            print(f"   EAN z faktury: {ean}")
            
            # Szukaj podobnych produktów
            if "Front Line Premium" in description:
                if "czarne" in description:
                    products = session.query(Product).filter(Product.name.like('%Front Line Premium%')).filter(Product.name.like('%czar%')).all()
                elif "czerwone" in description:
                    products = session.query(Product).filter(Product.name.like('%Front Line Premium%')).filter(Product.name.like('%czerwon%')).all()
            elif "Front Line" in description and "Premium" not in description:
                products = session.query(Product).filter(Product.name.like('%Front Line%')).filter(~Product.name.like('%Premium%')).filter(Product.name.like('%czar%')).all()
            else:
                products = []
            
            if products:
                print(f"   ✅ Znaleziono {len(products)} pasujących produktów:")
                for product in products:
                    print(f"      • [{product.id}] {product.name}")
                    sizes = session.query(ProductSize).filter_by(product_id=product.id).all()
                    for size in sizes:
                        status = "✓ MA EAN" if size.barcode else "✗ BRAK EAN"
                        print(f"        - Rozmiar: {size.size:10s} | Barcode: {size.barcode or 'BRAK':15s} | {status}")
            else:
                print(f"   ❌ NIE ZNALEZIONO pasujących produktów w bazie!")
            
            print("-" * 120)
        
        # Dodatkowo - pokaż wszystkie produkty Front Line Premium czarne
        print("\n" + "=" * 120)
        print("WSZYSTKIE PRODUKTY: Front Line Premium czarne")
        print("=" * 120)
        products = session.query(Product).filter(Product.name.like('%Front Line Premium%')).filter(Product.name.like('%czar%')).all()
        for product in products:
            print(f"\n[{product.id}] {product.name}")
            sizes = session.query(ProductSize).filter_by(product_id=product.id).all()
            for size in sizes:
                print(f"  {size.size:5s} | EAN: {size.barcode or 'BRAK'}")
        
        # Wszystkie Front Line (bez Premium) czarne
        print("\n" + "=" * 120)
        print("WSZYSTKIE PRODUKTY: Front Line (bez Premium) czarne")
        print("=" * 120)
        products = session.query(Product).filter(Product.name.like('%Front Line%')).filter(~Product.name.like('%Premium%')).filter(Product.name.like('%czar%')).all()
        for product in products:
            print(f"\n[{product.id}] {product.name}")
            sizes = session.query(ProductSize).filter_by(product_id=product.id).all()
            for size in sizes:
                print(f"  {size.size:5s} | EAN: {size.barcode or 'BRAK'}")
        
        # Wszystkie Front Line Premium czerwone
        print("\n" + "=" * 120)
        print("WSZYSTKIE PRODUKTY: Front Line Premium czerwone")
        print("=" * 120)
        products = session.query(Product).filter(Product.name.like('%Front Line Premium%')).filter(Product.name.like('%czerwon%')).all()
        for product in products:
            print(f"\n[{product.id}] {product.name}")
            sizes = session.query(ProductSize).filter_by(product_id=product.id).all()
            for size in sizes:
                print(f"  {size.size:5s} | EAN: {size.barcode or 'BRAK'}")
