#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Poprawia błędne mapowanie EAN dla Front Line Premium różowe
Z faktury: 6971818794822 = rozmiar S (nie XS!)
"""
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize
from magazyn.db import get_session

app = create_app()

with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 100)
        print("NAPRAWA: Front Line Premium różowe - EAN 6971818794822 powinien być dla S, nie XS")
        print("=" * 100)
        
        # 1. Usuń EAN z XS (ID 254)
        ps_xs = session.query(ProductSize).get(254)
        if ps_xs:
            print(f"\n1. Rozmiar XS (ID {ps_xs.id}):")
            print(f"   Przed: EAN = {ps_xs.barcode}, Ilość = {ps_xs.quantity}")
            ps_xs.barcode = None
            ps_xs.quantity = 0  # Zmień na 0 bo nie kupiliśmy XS
            print(f"   Po:    EAN = {ps_xs.barcode}, Ilość = {ps_xs.quantity}")
        
        # 2. Dodaj EAN do S (ID 255)
        ps_s = session.query(ProductSize).get(255)
        if ps_s:
            print(f"\n2. Rozmiar S (ID {ps_s.id}):")
            print(f"   Przed: EAN = {ps_s.barcode or 'BRAK'}, Ilość = {ps_s.quantity}")
            ps_s.barcode = '6971818794822'
            ps_s.quantity = 2  # Z faktury było 2 sztuki
            print(f"   Po:    EAN = {ps_s.barcode}, Ilość = {ps_s.quantity}")
        
        session.commit()
        
        print("\n" + "=" * 100)
        print("WERYFIKACJA:")
        print("=" * 100)
        
        # Sprawdź produkt 41
        sizes = session.query(ProductSize).filter_by(product_id=41).order_by(ProductSize.size).all()
        for ps in sizes:
            if ps.size in ['S', 'XS']:
                print(f"\n  {ps.size:5s} | EAN: {ps.barcode or 'BRAK':15s} | Ilość: {ps.quantity}")
        
        # Sprawdź czy EAN działa
        print("\n" + "=" * 100)
        print("TEST SKANOWANIA:")
        print("=" * 100)
        
        ps_test = session.query(ProductSize).filter_by(barcode='6971818794822').first()
        if ps_test:
            prod = session.query(Product).get(ps_test.product_id)
            print(f"\n✓ EAN 6971818794822 znaleziony:")
            print(f"  Produkt: {prod.name if prod else 'BRAK'}")
            print(f"  Rozmiar: {ps_test.size} (powinno być S)")
            print(f"  Ilość: {ps_test.quantity}")
        else:
            print("\n✗ EAN nie znaleziony!")
