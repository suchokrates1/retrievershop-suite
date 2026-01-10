#!/usr/bin/env python3
"""Debug paginacji API Allegro"""
from magazyn.settings_store import settings_store
from magazyn import allegro_api
from magazyn.factory import create_app
import json

app = create_app()
with app.app_context():
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not token:
        print("Brak tokena!")
        exit(1)
    
    # Pobierz pierwsza strone
    data = allegro_api.fetch_offers(token, offset=0, limit=100)
    
    print(f"Klucze w odpowiedzi: {list(data.keys())}")
    
    offers = data.get("offers", [])
    print(f"Ilosc ofert na stronie 1: {len(offers)}")
    
    # Sprawdz paginacje
    print(f"\nnextPage: {data.get('nextPage')}")
    print(f"links: {data.get('links')}")
    print(f"totalCount: {data.get('totalCount')}")
    print(f"count: {data.get('count')}")
    
    # Jezeli jest totalCount, sprawdz czy trzeba pobrac wiecej
    total = data.get("totalCount")
    if total:
        print(f"\nTotal ofert: {total}")
        if total > 100:
            print(f"Potrzebna druga strona! (offset=100)")
            
            # Pobierz druga strone
            data2 = allegro_api.fetch_offers(token, offset=100, limit=100)
            offers2 = data2.get("offers", [])
            print(f"Ilosc ofert na stronie 2: {len(offers2)}")
