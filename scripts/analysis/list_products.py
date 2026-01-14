#!/usr/bin/env python3
"""Wyswietl produkty Front Line Premium i Blossom"""
from magazyn.models import Product
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        print("=== Front Line Premium ===")
        products = db.query(Product).filter(Product.name.contains('Front Line')).all()
        for p in products:
            print(f'{p.id}: {p.name}')
        
        print("\n=== Blossom ===")
        products = db.query(Product).filter(Product.name.contains('Blossom')).all()
        for p in products:
            print(f'{p.id}: {p.name}')
