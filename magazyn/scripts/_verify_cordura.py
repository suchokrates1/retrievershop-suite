"""Szybka weryfikacja: czy oferty Cordura maja poprawne product_id i product_size_id."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from magazyn.db import configure_engine, get_session
from magazyn.models import AllegroOffer

configure_engine()

with get_session() as s:
    for oid in ['17768380937', '18370786950', '18332420996', '18358308246']:
        o = s.query(AllegroOffer).filter(AllegroOffer.offer_id == oid).first()
        if o:
            print(f"{oid}: pid={o.product_id}, ps={o.product_size_id}, cena={o.price}")
        else:
            print(f"{oid}: NIE ZNALEZIONO")
