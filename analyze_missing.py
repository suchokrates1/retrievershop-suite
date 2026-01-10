#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dodaje brakujące EAN-y do odpowiednich produktów
"""
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize
from magazyn.db import get_session

app = create_app()

# Mapowanie: EAN z faktury -> produkt + rozmiar w bazie
missing_mappings = [
    # 6971818794709 - Front Line Premium czarne XL -> który produkt?
    # 6971818794679 - Front Line Premium czarne S -> który produkt?
    # 6971818795126 - Front Line Premium czerwone S -> produkt 37 ma M i L czerwone, ale brak S!
    # 6970117170184 - Front Line (bez Premium) czarne M -> brak M w id 75
]

with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 120)
        print("ANALIZA: Które warianty/rozmiary brakują w bazie")
        print("=" * 120)
        
        # Sprawdź Front Line Premium - powinny być XL, L, M, S, XS dla każdego koloru
        # ID 36 ma pełne rozmiary (L,M,S,XL,XS) - to są szare?
        # ID 40 ma S - to pomarańczowe
        # ID 41 ma XS - to różowe
        
        print("\n🔍 FRONT LINE PREMIUM - analiza kolorów:")
        premium_products = session.query(Product).filter(
            Product.name.like('%Front Line Premium%'),
            ~Product.name.like('%Cordura%')
        ).order_by(Product.id).all()
        
        for product in premium_products:
            print(f"\n[{product.id}] {product.name}")
            sizes = session.query(ProductSize).filter_by(product_id=product.id).order_by(ProductSize.size).all()
            
            # Pokaż rozmiary z EAN
            ean_sizes = {}
            for size in sizes:
                if size.barcode:
                    ean_sizes[size.size] = size.barcode
            
            if ean_sizes:
                print(f"   Rozmiary z EAN: {', '.join(sorted(ean_sizes.keys()))}")
                for sz, ean in sorted(ean_sizes.items()):
                    print(f"      {sz:5s}: {ean}")
            
            # Pokaż brakujące rozmiary (zakładając że powinny być: XS,S,M,L,XL,2XL)
            all_expected = {'XS', 'S', 'M', 'L', 'XL', '2XL'}
            existing = set(sz.size for sz in sizes if sz.size != 'Uniwersalny')
            missing = all_expected - existing
            if missing:
                print(f"   ⚠️  Brakujące rozmiary w bazie: {', '.join(sorted(missing))}")
            
            # Pokaż rozmiary BEZ EAN
            no_ean = [sz.size for sz in sizes if not sz.barcode and sz.size != 'Uniwersalny']
            if no_ean:
                print(f"   ❌ Rozmiary bez EAN: {', '.join(sorted(no_ean))}")
        
        print("\n" + "=" * 120)
        print("🔍 FRONT LINE (bez Premium) - analiza:")
        print("=" * 120)
        
        front_products = session.query(Product).filter(
            Product.name.like('%Front Line%'),
            ~Product.name.like('%Premium%'),
            ~Product.name.like('%easy walk%')
        ).order_by(Product.id).all()
        
        for product in front_products:
            print(f"\n[{product.id}] {product.name}")
            sizes = session.query(ProductSize).filter_by(product_id=product.id).order_by(ProductSize.size).all()
            
            ean_sizes = {}
            for size in sizes:
                if size.barcode:
                    ean_sizes[size.size] = size.barcode
            
            if ean_sizes:
                print(f"   Rozmiary z EAN: {', '.join(sorted(ean_sizes.keys()))}")
            
            no_ean = [sz.size for sz in sizes if not sz.barcode and sz.size != 'Uniwersalny']
            if no_ean:
                print(f"   ❌ Rozmiary bez EAN: {', '.join(sorted(no_ean))}")
        
        print("\n" + "=" * 120)
        print("WNIOSKI:")
        print("=" * 120)
        print("""
Brakujące EAN-y z faktury to produkty, które NIE ISTNIEJĄ w bazie jako osobne warianty:

1. 6971818794709 - Front Line Premium czarne XL
2. 6971818794679 - Front Line Premium czarne S
3. 6971818795126 - Front Line Premium czerwone S (ID 37 ma M,L,XL ale brak S!)
4. 6970117170184 - Front Line czarne M (ID 75 ma tylko L,XL,XS ale brak M,S!)

ROZWIĄZANIE:
1. Sprawdź który produkt Front Line Premium to wersja "czarna" 
2. Dodaj brakujące rozmiary (XL i S) do tego produktu z odpowiednimi EAN
3. W produkcie ID 37 (czerwone) dodaj rozmiar S z EAN 6971818795126
4. W produkcie ID 75 (Front Line czarne) dodaj rozmiar M z EAN 6970117170184
        """)
