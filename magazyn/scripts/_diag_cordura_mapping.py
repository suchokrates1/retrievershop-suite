"""Diagnostyka: jak wyglada mapowanie ofert Cordura w bazie."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from magazyn.db import get_session
from magazyn.models import AllegroOffer, Product, ProductSize

with get_session() as s:
    # Znajdz oferty z "Cordura" w tytule
    cordura_offers = s.query(AllegroOffer).filter(
        AllegroOffer.title.ilike('%cordura%'),
        AllegroOffer.publication_status == 'ACTIVE'
    ).all()
    
    print(f"=== AKTYWNE OFERTY CORDURA: {len(cordura_offers)} ===\n")
    
    ps_ids = set()
    product_ids = set()
    
    for o in cordura_offers:
        ps = s.query(ProductSize).filter(ProductSize.id == o.product_size_id).first() if o.product_size_id else None
        prod = s.query(Product).filter(Product.id == o.product_id).first() if o.product_id else None
        
        print(f"offer_id={o.offer_id}")
        print(f"  tytul: {o.title}")
        print(f"  cena: {o.price} zl")
        print(f"  product_id={o.product_id} -> {prod.name if prod else 'BRAK'}")
        if prod:
            print(f"    category={prod.category}, brand={prod.brand}, series={prod.series}, color={prod.color}")
            product_ids.add(o.product_id)
        print(f"  product_size_id={o.product_size_id} -> rozmiar={ps.size if ps else 'BRAK'}, ps.product_id={ps.product_id if ps else 'BRAK'}")
        if ps:
            ps_ids.add(o.product_size_id)
        print()
    
    # Dla kazdego product_size_id Cordury - pokaz WSZYSTKIE oferty na tym ps_id
    print(f"\n=== WSZYSTKIE OFERTY NA TYM SAMYM PRODUCT_SIZE_ID ===\n")
    for ps_id in sorted(ps_ids):
        ps = s.query(ProductSize).filter(ProductSize.id == ps_id).first()
        all_offers = s.query(AllegroOffer).filter(
            AllegroOffer.product_size_id == ps_id,
            AllegroOffer.publication_status == 'ACTIVE'
        ).order_by(AllegroOffer.price).all()
        
        print(f"--- product_size_id={ps_id} (rozmiar={ps.size}, product_id={ps.product_id}) ---")
        for o in all_offers:
            is_cordura = 'cordura' in (o.title or '').lower()
            marker = " *** CORDURA ***" if is_cordura else ""
            print(f"  {o.offer_id}: {o.price} zl | pid={o.product_id} | {o.title[:80]}{marker}")
        print()
    
    # Pokaz produkty Cordura
    print(f"\n=== PRODUKTY DO KTORYCH PRZYPISANO CORDURA ===\n")
    for pid in sorted(product_ids):
        prod = s.query(Product).filter(Product.id == pid).first()
        sizes = s.query(ProductSize).filter(ProductSize.product_id == pid).all()
        print(f"Product id={pid}: {prod.name}")
        print(f"  category={prod.category}, brand={prod.brand}, series={prod.series}, color={prod.color}")
        print(f"  rozmiary: {[(sz.id, sz.size) for sz in sizes]}")
        
        # Ile ofert na kazdym rozmiarze
        for sz in sizes:
            offers_on_sz = s.query(AllegroOffer).filter(
                AllegroOffer.product_size_id == sz.id,
                AllegroOffer.publication_status == 'ACTIVE'
            ).all()
            if offers_on_sz:
                print(f"    ps_id={sz.id} ({sz.size}): {len(offers_on_sz)} ofert -> {[(o.offer_id, float(o.price), 'CORDURA' if 'cordura' in (o.title or '').lower() else '') for o in offers_on_sz]}")
        print()
    
    # Czy istnieje osobny Product z "Cordura" w series?
    cordura_products = s.query(Product).filter(
        (Product.series.ilike('%cordura%')) | (Product._name.ilike('%cordura%'))
    ).all()
    print(f"\n=== PRODUKTY Z 'CORDURA' W NAZWIE/SERII: {len(cordura_products)} ===")
    for p in cordura_products:
        print(f"  id={p.id}: {p.name} (category={p.category}, series={p.series}, color={p.color})")
