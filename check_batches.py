#!/usr/bin/env python3
import os
os.environ['FLASK_APP'] = 'magazyn.factory:create_app'

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import Product, ProductSize, PurchaseBatch
from sqlalchemy import desc
from collections import defaultdict

app = create_app()

with app.app_context():
    with get_session() as session:
        # Najpierw sprawdzam wszystkie
        all_batches = session.query(PurchaseBatch).order_by(desc(PurchaseBatch.id)).limit(50).all()
        print(f'Ostatnich 50 partii zakupowych:')
        print('='*120)
        
        for batch in all_batches:
            product = batch.product if batch.product else None
            size_name = batch.size
            purchase_date = batch.purchase_date if batch.purchase_date else 'BRAK'
            barcode = batch.barcode if batch.barcode else 'BRAK'
            
            if product:
                print(f'{batch.id:4d} | Data: {str(purchase_date)[:10]:10s} | {product.name[:35]:35s} | {size_name:10s} | {batch.quantity:3d} szt | EAN: {barcode}')
