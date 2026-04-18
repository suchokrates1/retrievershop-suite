"""Sprawdz ProductSizes na Products Cordura i napraw przypisanie ofert."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from magazyn.db import configure_engine, get_session
from magazyn.models import AllegroOffer, Product, ProductSize

configure_engine()

with get_session() as s:
    # Pokaz produkty Cordura
    for pid in [76, 77]:
        p = s.query(Product).filter(Product.id == pid).first()
        if not p:
            print(f"Product {pid}: NIE ISTNIEJE")
            continue
        sizes = s.query(ProductSize).filter(ProductSize.product_id == pid).all()
        print(f"Product {pid}: {p.name}")
        print(f"  series={p.series}, color={p.color}")
        print(f"  rozmiary: {[(sz.id, sz.size) for sz in sizes]}")
        
        # Oferty na kazdym rozmiarze
        for sz in sizes:
            offers = s.query(AllegroOffer).filter(
                AllegroOffer.product_size_id == sz.id,
                AllegroOffer.publication_status == 'ACTIVE'
            ).all()
            if offers:
                print(f"    ps={sz.id} ({sz.size}): {[(o.offer_id, float(o.price)) for o in offers]}")
        print()
    
    # Pokaz blednie przypisane oferty Cordura
    print("=== BLEDNIE PRZYPISANE OFERTY CORDURA ===")
    cordura_offers = s.query(AllegroOffer).filter(
        AllegroOffer.title.ilike('%cordura%'),
        AllegroOffer.publication_status == 'ACTIVE'
    ).all()
    
    for o in cordura_offers:
        ps = s.query(ProductSize).filter(ProductSize.id == o.product_size_id).first()
        prod = s.query(Product).filter(Product.id == o.product_id).first()
        is_on_cordura_product = prod and 'cordura' in (prod.series or '').lower()
        status = "OK" if is_on_cordura_product else "BLEDNE"
        print(f"  [{status}] {o.offer_id}: pid={o.product_id} ({prod.series if prod else '?'}), "
              f"ps={o.product_size_id} ({ps.size if ps else '?'}), {float(o.price)} zl")
        print(f"    tytul: {o.title}")
