#!/usr/bin/env python3
"""Sprawdz pas do biegania i amortyzator w magazynie"""
from magazyn.models import Product, ProductSize
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        print("=== Pas do biegania ===")
        products = db.query(Product).filter(Product.name.ilike('%pas%bieg%')).all()
        if not products:
            products = db.query(Product).filter(Product.name.ilike('%dogtrekking%')).all()
        if not products:
            products = db.query(Product).filter(Product.name.ilike('%pas%')).all()
        
        for p in products:
            print(f'{p.id}: {p.name} (kolor: {p.color})')
            for ps in p.sizes:
                print(f'  {ps.size}: barcode={ps.barcode or "BRAK"}')
        
        if not products:
            print("BRAK produktow z 'pas' w nazwie")
        
        print("\n=== Amortyzator ===")
        products = db.query(Product).filter(Product.name.ilike('%amortyzator%')).all()
        for p in products:
            print(f'{p.id}: {p.name} (kolor: {p.color})')
            for ps in p.sizes:
                print(f'  {ps.size}: barcode={ps.barcode or "BRAK"}')
        
        print("\n=== Wszystkie produkty z 'Truelove' ===")
        products = db.query(Product).filter(Product.name.ilike('%truelove%')).all()
        unique_types = set()
        for p in products:
            # Wyciagnij typ produktu
            name = p.name.replace('Szelki dla psa Truelove ', '').replace('Truelove ', '')
            unique_types.add(name.split()[0] if name.split() else name)
        print(f"Typy produktow: {sorted(unique_types)}")
