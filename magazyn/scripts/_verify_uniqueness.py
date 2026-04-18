"""Weryfikacja: czy (category, series, color) jednoznacznie identyfikuje produkt."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from collections import Counter
from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import Product

app = create_app()
with app.app_context():
    with get_session() as s:
        products = s.query(Product).all()
        keys = []
        for p in products:
            key = (p.category, p.series, p.color)
            keys.append(key)

        dupes = [(k, c) for k, c in Counter(keys).items() if c > 1]
        if dupes:
            print("DUPLIKATY (category, series, color):")
            for k, c in dupes:
                print(f"  {k}: {c}x")
                for p in products:
                    if (p.category, p.series, p.color) == k:
                        print(f"    id={p.id} name={p.name}")
        else:
            print(f"OK: {len(products)} produktow, kazdy (category, series, color) jest unikalny")
