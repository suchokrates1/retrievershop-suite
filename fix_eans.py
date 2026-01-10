#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Naprawia brakujące/błędne EAN-y w bazie
"""
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize
from magazyn.db import get_session

app = create_app()

fixes = []

with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 120)
        print("NAPRAWIANIE BRAKUJĄCYCH EAN-ÓW")
        print("=" * 120)
        
        # 1. Produkt ID 36 (Front Line Premium czarne) - zmień EAN dla XL i S
        print("\n1️⃣  Produkt ID 36 - Front Line Premium (czarne)")
        
        # XL - zmień z 4058543578001 na 6971818794709
        ps_xl = session.query(ProductSize).filter_by(product_id=36, size='XL').first()
        if ps_xl:
            old_ean = ps_xl.barcode
            ps_xl.barcode = '6971818794709'
            fixes.append(f"   ✓ XL: {old_ean} → 6971818794709")
        
        # S - zmień z 4058543576847 na 6971818794679
        ps_s = session.query(ProductSize).filter_by(product_id=36, size='S').first()
        if ps_s:
            old_ean = ps_s.barcode
            ps_s.barcode = '6971818794679'
            fixes.append(f"   ✓ S:  {old_ean} → 6971818794679")
        
        # 2. Produkt ID 37 (Front Line Premium czerwone) - dodaj rozmiar S
        print("\n2️⃣  Produkt ID 37 - Front Line Premium (czerwone) - dodaj rozmiar S")
        ps_red_s = session.query(ProductSize).filter_by(product_id=37, size='S').first()
        if not ps_red_s:
            new_size = ProductSize(
                product_id=37,
                size='S',
                quantity=0,  # Zostanie zaktualizowane z purchase_batch
                barcode='6971818795126'
            )
            session.add(new_size)
            fixes.append(f"   ✓ Dodano rozmiar S z EAN 6971818795126")
        else:
            ps_red_s.barcode = '6971818795126'
            fixes.append(f"   ✓ Zaktualizowano rozmiar S → EAN 6971818795126")
        
        # 3. Produkt ID 75 (Front Line czarne bez Premium) - dodaj rozmiar M
        print("\n3️⃣  Produkt ID 75 - Front Line (czarne, bez Premium) - dodaj rozmiar M")
        ps_fl_m = session.query(ProductSize).filter_by(product_id=75, size='M').first()
        if not ps_fl_m:
            new_size = ProductSize(
                product_id=75,
                size='M',
                quantity=0,
                barcode='6970117170184'
            )
            session.add(new_size)
            fixes.append(f"   ✓ Dodano rozmiar M z EAN 6970117170184")
        else:
            ps_fl_m.barcode = '6970117170184'
            fixes.append(f"   ✓ Zaktualizowano rozmiar M → EAN 6970117170184")
        
        # Commituj zmiany
        session.commit()
        
        print("\n" + "=" * 120)
        print("PODSUMOWANIE ZMIAN:")
        print("=" * 120)
        for fix in fixes:
            print(fix)
        
        print("\n" + "=" * 120)
        print("WERYFIKACJA - sprawdzam czy wszystkie EAN-y z faktury są teraz w bazie:")
        print("=" * 120)
        
        invoice_eans = [
            ('6976128181232', 'Pas samochodowy'),
            ('6971818794709', 'Front Line Premium czarne XL'),
            ('6971818794679', 'Front Line Premium czarne S'),
            ('6971818795102', 'Front Line Premium brązowe XL'),
            ('6971818794822', 'Front Line Premium różowe S'),
            ('6971818795133', 'Front Line Premium czerwone M'),
            ('6971818795126', 'Front Line Premium czerwone S'),
            ('6971818794747', 'Front Line Premium pomarańczowe L'),
            ('6971818794723', 'Front Line Premium pomarańczowe S'),
            ('6971818795188', 'Tropical turkusowe M'),
            ('6970117170207', 'Front Line czarne XL'),
            ('6970117170184', 'Front Line czarne M'),
            ('6970117170641', 'Active czarny XL'),
            ('6970117170634', 'Active czarny L'),
            ('6970117170627', 'Active czarny M'),
            ('6971273110694', 'Outdoor czerwony 2XL'),
            ('6970117178500', 'easy walk brązowe XL'),
            ('6970117178494', 'easy walk brązowe L'),
            ('6970117178487', 'easy walk brązowe M'),
        ]
        
        for ean, desc in invoice_eans:
            ps = session.query(ProductSize).filter_by(barcode=ean).first()
            if ps:
                product = session.query(Product).get(ps.product_id)
                print(f"✓ {ean} | {desc:40s} | Znaleziono: [{ps.product_id}] {product.name} {ps.size}")
            else:
                print(f"✗ {ean} | {desc:40s} | NADAL BRAK W BAZIE!")
