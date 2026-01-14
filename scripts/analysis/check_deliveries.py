import sys
sys.path.insert(0, '/c/Users/sucho/retrievershop-suite')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize, PurchaseBatch
from sqlalchemy import desc

app = create_app()

with app.app_context():
    from magazyn.db import get_session
    
    with get_session() as session:
        # Ostatnie partie zakupowe
        batches = session.query(PurchaseBatch).filter(
            PurchaseBatch.purchase_date >= '2026-01-01'
        ).order_by(desc(PurchaseBatch.purchase_date)).limit(50).all()
        
        print(f'Znalezionych dostaw od 2026-01-01: {len(batches)}')
        print('='*120)
        
        # Grupujemy po dacie zakupu
        from collections import defaultdict
        by_date = defaultdict(list)
        for batch in batches:
            date_str = batch.purchase_date.strftime('%Y-%m-%d') if batch.purchase_date else 'brak daty'
            by_date[date_str].append(batch)
        
        for date_str in sorted(by_date.keys(), reverse=True):
            items = by_date[date_str]
            print(f'\nData zakupu: {date_str} ({len(items)} produktów)')
            print('-'*120)
            for batch in items:
                product = batch.product_size.product if batch.product_size else None
                size = batch.product_size
                if product and size:
                    print(f'  {batch.id:4d}. {product.name[:45]:45s} | {size.name:15s} | {batch.quantity:3d} szt | EAN: {size.barcode or "BRAK"}')
                else:
                    print(f'  {batch.id:4d}. PRODUKT USUNIĘTY | {batch.quantity:3d} szt')
