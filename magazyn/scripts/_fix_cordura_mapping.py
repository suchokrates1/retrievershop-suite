"""Naprawa: przeniesienie ofert Cordura na wlasciwe produkty.

Oferty Cordura sa blednie przypisane do zwyklych produktow Front Line / Front Line Premium.
Prawidlowe przypisanie:
  - 17768380937 (FL Premium Cordura XL czarne)  -> Product 76, ps=410 (XL)
  - 18370786950 (FL Premium Cordura L czarne)    -> Product 76, ps=409 (L)
  - 18332420996 (FL Cordura XL pomaranczowe)     -> Product 77, ps=416 (XL)
  - 18358308246 (FL Cordura L pomaranczowe)      -> Product 77, ps=415 (L)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from magazyn.db import configure_engine, get_session
from magazyn.models import AllegroOffer, ProductSize

configure_engine()

# Mapowanie: offer_id -> (product_id, product_size_id)
FIXES = {
    '17768380937': (76, 410),  # FL Premium Cordura XL czarne
    '18370786950': (76, 409),  # FL Premium Cordura L czarne
    '18332420996': (77, 416),  # FL Cordura XL pomaranczowe
    '18358308246': (77, 415),  # FL Cordura L pomaranczowe
}

with get_session() as s:
    for offer_id, (new_pid, new_ps_id) in FIXES.items():
        offer = s.query(AllegroOffer).filter(AllegroOffer.offer_id == offer_id).first()
        if not offer:
            print(f"BLAD: Oferta {offer_id} nie znaleziona!")
            continue
        
        # Weryfikacja docelowego ProductSize
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
        
        print(f"OK: {offer_id} ({offer.title[:60]})")
        print(f"  pid: {old_pid} -> {new_pid}")
        print(f"  ps:  {old_ps} -> {new_ps_id} ({target_ps.size})")
    
    s.commit()
    print("\nZapisano zmiany.")
