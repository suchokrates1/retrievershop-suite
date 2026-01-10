#!/usr/bin/env python3
"""Wyswietl szczegoly produktow Front Line Premium z barcodeami"""
from magazyn.models import Product, ProductSize
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        print("=== Front Line Premium z barcodami ===")
        products = db.query(Product).filter(Product.name.contains('Front Line Premium')).all()
        
        for p in products:
            # Znajdz rozmiary z barcodeami
            sizes_with_barcode = db.query(ProductSize).filter(
                ProductSize.product_id == p.id,
                ProductSize.barcode.isnot(None),
                ProductSize.barcode != ''
            ).all()
            
            if sizes_with_barcode:
                print(f'\nProdukt ID={p.id}: {p.name}')
                if hasattr(p, 'color'):
                    print(f'  Kolor: {p.color}')
                for ps in sizes_with_barcode:
                    print(f'  - {ps.size}: {ps.barcode}')
