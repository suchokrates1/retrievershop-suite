#!/usr/bin/env python3
"""Sprawdź dlaczego EAN 6971273110694 nie matchuje się"""

from magazyn.factory import create_app
from magazyn.models import ProductSize, OrderProduct
from magazyn.db import get_session

app = create_app()

with app.app_context():
    with get_session() as db:
        # Szukaj w product_sizes
        ps = db.query(ProductSize).filter(ProductSize.barcode == '6971273110694').first()
        if ps:
            print(f"✅ ProductSize znaleziony:")
            print(f"   ID: {ps.id}")
            print(f"   Product: {ps.product.name if ps.product else 'None'}")
            print(f"   Size: {ps.size}")
            print(f"   Barcode: {repr(ps.barcode)}")
            print(f"   Barcode len: {len(ps.barcode)}")
            print(f"   Barcode bytes: {ps.barcode.encode('utf-8')}")
        else:
            print("❌ ProductSize NIE znaleziony")
            # Szukaj z LIKE
            ps_like = db.query(ProductSize).filter(ProductSize.barcode.like('%6971273110694%')).all()
            if ps_like:
                print(f"Znaleziono {len(ps_like)} z LIKE:")
                for p in ps_like:
                    print(f"  - {repr(p.barcode)} (len={len(p.barcode)})")
            else:
                print("Też nic z LIKE")
        
        print()
        
        # Szukaj w order_products
        ops = db.query(OrderProduct).filter(OrderProduct.ean == '6971273110694').all()
        if ops:
            print(f"✅ OrderProduct znaleziony ({len(ops)} zamówień):")
            for op in ops[:3]:  # Pierwsze 3
                print(f"   Order ID: {op.order_id}")
                print(f"   Name: {op.name}")
                print(f"   EAN: {repr(op.ean)}")
                print(f"   EAN len: {len(op.ean) if op.ean else 0}")
                if op.ean:
                    print(f"   EAN bytes: {op.ean.encode('utf-8')}")
                print()
        else:
            print("❌ OrderProduct NIE znaleziony")
            # Szukaj z LIKE
            ops_like = db.query(OrderProduct).filter(OrderProduct.ean.like('%6971273110694%')).all()
            if ops_like:
                print(f"Znaleziono {len(ops_like)} z LIKE:")
                for op in ops_like[:3]:
                    print(f"  - {repr(op.ean)} (len={len(op.ean) if op.ean else 0})")
