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
        print("\n" + "=" * 120)
        print("WSZYSTKIE PRODUKTY ZAWIERAJĄCE 'Truelove' lub 'Front'")
        print("=" * 120)
        
        products = session.query(Product).filter(
            (Product.name.like('%Truelove%')) | (Product.name.like('%Front%'))
        ).order_by(Product.name).all()
        
        for product in products:
            print(f"\n[{product.id:3d}] {product.name}")
            sizes = session.query(ProductSize).filter_by(product_id=product.id).order_by(ProductSize.size).all()
            for size in sizes:
                ean_status = f"✓ {size.barcode}" if size.barcode else "✗ BRAK EAN"
                print(f"      {size.size:5s} | {ean_status}")
