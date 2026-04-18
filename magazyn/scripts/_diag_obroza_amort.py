"""Diagnostyka: obroza Lumen, ENDED Cordura, amortyzator - dane do naprawy."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import AllegroOffer, Product, ProductSize

app = create_app()
with app.app_context():
    with get_session() as s:
        # Obroza Lumen - produkty i rozmiary
        print("=== OBROZA LUMEN - PRODUKTY DOCELOWE ===")
        for pid in [95, 100]:
            p = s.query(Product).filter(Product.id == pid).first()
            sizes = s.query(ProductSize).filter(ProductSize.product_id == pid).order_by(ProductSize.id).all()
            print(f"Product {pid}: {p.name} (color={p.color})")
            for sz in sizes:
                print(f"  ps_id={sz.id} size={sz.size}")

        print("\n=== BLEDNE OBROZE LUMEN (na szelkach) ===")
        for oid in ['18314238132', '18314255166', '18314088528', '18314105200']:
            o = s.query(AllegroOffer).filter(AllegroOffer.offer_id == oid).first()
            if o:
                ps = s.query(ProductSize).filter(ProductSize.id == o.product_size_id).first()
                print(f"{oid}: pid={o.product_id} ps={o.product_size_id} size={ps.size if ps else None} price={o.price} status={o.publication_status}")
                print(f"  title: {o.title[:120]}")

        print("\n=== ENDED CORDURA ===")
        for oid in ['17768440635', '17768469573', '18025414629', '17768491806']:
            o = s.query(AllegroOffer).filter(AllegroOffer.offer_id == oid).first()
            if o:
                ps = s.query(ProductSize).filter(ProductSize.id == o.product_size_id).first()
                print(f"{oid}: pid={o.product_id} ps={o.product_size_id} size={ps.size if ps else None} price={o.price} status={o.publication_status}")
                print(f"  title: {o.title[:120]}")

        print("\n=== AMORTYZATOR ===")
        o = s.query(AllegroOffer).filter(AllegroOffer.offer_id == '17881284159').first()
        if o:
            ps = s.query(ProductSize).filter(ProductSize.id == o.product_size_id).first()
            print(f"17881284159: pid={o.product_id} ps={o.product_size_id} size={ps.size if ps else None} price={o.price} status={o.publication_status}")
            print(f"  title: {o.title[:120]}")

        # Cordura rozmiary  
        print("\n=== CORDURA - PRODUKTY DOCELOWE ===")
        for pid in [76, 77]:
            p = s.query(Product).filter(Product.id == pid).first()
            sizes = s.query(ProductSize).filter(ProductSize.product_id == pid).order_by(ProductSize.id).all()
            print(f"Product {pid}: {p.name} (color={p.color})")
            for sz in sizes:
                print(f"  ps_id={sz.id} size={sz.size}")

        # Amortyzator produkty
        print("\n=== AMORTYZATOR - PRODUKTY W DB ===")
        amort_prods = s.query(Product).filter(Product.category.ilike('%Amortyzator%')).all()
        for p in amort_prods:
            sizes = s.query(ProductSize).filter(ProductSize.product_id == p.id).order_by(ProductSize.id).all()
            print(f"Product {p.id}: {p.name} (color={p.color})")
            for sz in sizes:
                print(f"  ps_id={sz.id} size={sz.size}")
