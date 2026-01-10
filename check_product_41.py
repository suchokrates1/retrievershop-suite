#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize
from magazyn.db import get_session

app = create_app()

with app.app_context():
    with get_session() as session:
        print("\n" + "=" * 100)
        print("PRODUKT ID 41 - Front Line Premium różowe")
        print("=" * 100)
        
        product = session.query(Product).get(41)
        if product:
            print(f"\n[{product.id}] {product.name}")
            
            sizes = session.query(ProductSize).filter_by(product_id=41).order_by(ProductSize.size).all()
            for ps in sizes:
                print(f"\n  Rozmiar: {ps.size}")
                print(f"    ID: {ps.id}")
                print(f"    EAN: {ps.barcode or 'BRAK'}")
                print(f"    Ilość: {ps.quantity}")
        else:
            print("Produkt nie znaleziony!")
        
        print("\n" + "=" * 100)
        print("Szukam EAN 6971818794822 w bazie:")
        print("=" * 100)
        
        ps = session.query(ProductSize).filter_by(barcode='6971818794822').first()
        if ps:
            prod = session.query(Product).get(ps.product_id)
            print(f"\nZnaleziono:")
            print(f"  Produkt: [{ps.product_id}] {prod.name if prod else 'BRAK'}")
            print(f"  Rozmiar: {ps.size}")
            print(f"  ProductSize ID: {ps.id}")
            print(f"  Ilość: {ps.quantity}")
        else:
            print("\nNIE ZNALEZIONO!")
