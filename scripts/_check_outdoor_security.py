"""Sprawdz produkty Outdoor i Security w bazie produkcyjnej."""
from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import Product, ProductSize, PurchaseBatch

app = create_app()
with app.app_context():
    with get_session() as db:
        for series in ['Outdoor', 'Security']:
            products = db.query(Product).filter_by(series=series).all()
            print(f'--- {series} ({len(products)} produktow) ---')
            for p in products:
                sizes = db.query(ProductSize).filter_by(product_id=p.id).all()
                batches = db.query(PurchaseBatch).filter_by(product_id=p.id).order_by(PurchaseBatch.purchase_date).all()
                print(f'  id={p.id} kat={p.category} seria={p.series} kolor={p.color}')
                for s in sizes:
                    print(f'    rozm={s.size} qty={s.quantity} barcode={s.barcode}')
                for b in batches:
                    print(f'    batch id={b.id} size={b.size} qty={b.quantity} rem={b.remaining_quantity} inv={b.invoice_number} date={b.purchase_date}')
        # Szukaj tez po nazwie/name - moze istnialy pod inna nazwa
        print()
        print('--- Szukam po nazwie _name zawierajacej Outdoor lub Security ---')
        old_prods = db.query(Product).filter(
            Product._name.ilike('%outdoor%') | Product._name.ilike('%security%')
        ).all()
        for p in old_prods:
            sizes = db.query(ProductSize).filter_by(product_id=p.id).all()
            batches = db.query(PurchaseBatch).filter_by(product_id=p.id).order_by(PurchaseBatch.purchase_date).all()
            print(f'  id={p.id} name={p._name} kat={p.category} seria={p.series} kolor={p.color}')
            for s in sizes:
                print(f'    rozm={s.size} qty={s.quantity} barcode={s.barcode}')
            for b in batches:
                print(f'    batch id={b.id} size={b.size} qty={b.quantity} rem={b.remaining_quantity} inv={b.invoice_number} date={b.purchase_date}')
