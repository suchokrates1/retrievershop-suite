"""Naprawa: obroze Lumen, ENDED Cordura i amortyzator - przypisanie do wlasciwych produktow.

Obroze Lumen sa blednie przypisane do Szelek Lumen (pid=63/64) zamiast Obrozy Lumen (pid=95/100).
ENDED Cordura sa na zwyklych Front Line (pid=36/40) zamiast Cordura (pid=76/77).
Amortyzator zolty nie ma odpowiednika w bazie - ustawiamy NULL.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import AllegroOffer, ProductSize

app = create_app()
with app.app_context():
    # Mapowanie: offer_id -> (new_product_id, new_product_size_id)
    FIXES = {
        # Obroza Lumen czarna
        '18314238132': (100, 492),  # czarna L -> Obroza Lumen czarny L
        '18314255166': (100, 493),  # czarna M -> Obroza Lumen czarny M
        # Obroza Lumen zolta
        '18314088528': (95, 481),   # zolta L -> Obroza Lumen zolty L
        '18314105200': (95, 482),   # zolta M -> Obroza Lumen zolty M
        # ENDED Cordura czarna
        '17768440635': (76, 409),   # czarna L -> FL Premium Cordura Czarny L
        # ENDED Cordura pomaranczowa
        '17768469573': (77, 415),   # pomaranczowa L -> FL Premium Cordura Pomaranczowy L
        '18025414629': (77, 415),   # pomaranczowa L -> FL Premium Cordura Pomaranczowy L
        '17768491806': (77, 416),   # pomaranczowa XL -> FL Premium Cordura Pomaranczowy XL
    }

    # Amortyzator - brak zoltego w DB, ustawiamy NULL
    NULL_OFFERS = ['17881284159']

    with get_session() as s:
        print("=== NAPRAWA PRZYPISANIA OFERT ===\n")

        for offer_id, (new_pid, new_ps_id) in FIXES.items():
            offer = s.query(AllegroOffer).filter(AllegroOffer.offer_id == offer_id).first()
            if not offer:
                print(f"BLAD: Oferta {offer_id} nie znaleziona!")
                continue

            target_ps = s.query(ProductSize).filter(ProductSize.id == new_ps_id).first()
            if not target_ps:
                print(f"BLAD: ProductSize {new_ps_id} nie istnieje!")
                continue
            if target_ps.product_id != new_pid:
                print(f"BLAD: ProductSize {new_ps_id} nalezy do product_id={target_ps.product_id}, nie {new_pid}!")
                continue

            old_pid = offer.product_id
            old_ps = offer.product_size_id

            offer.product_id = new_pid
            offer.product_size_id = new_ps_id

            print(f"OK: {offer_id} ({offer.title[:80]})")
            print(f"  pid: {old_pid} -> {new_pid}")
            print(f"  ps:  {old_ps} -> {new_ps_id} ({target_ps.size})")
            print(f"  status: {offer.publication_status}\n")

        for offer_id in NULL_OFFERS:
            offer = s.query(AllegroOffer).filter(AllegroOffer.offer_id == offer_id).first()
            if not offer:
                print(f"BLAD: Oferta {offer_id} nie znaleziona!")
                continue

            old_pid = offer.product_id
            old_ps = offer.product_size_id

            offer.product_id = None
            offer.product_size_id = None

            print(f"NULL: {offer_id} ({offer.title[:80]})")
            print(f"  pid: {old_pid} -> None (brak zoltego amortyzatora w DB)")
            print(f"  ps:  {old_ps} -> None\n")

        s.commit()
        print("Zmiany zapisane.")
