"""Wybor 10 ofert do testu E2E price checkera."""
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app

app = create_app()

with app.app_context():
    from magazyn.db import get_session
    from magazyn.models import AllegroOffer
    from sqlalchemy import func

    with get_session() as s:
        offers = s.query(AllegroOffer).filter(
            AllegroOffer.publication_status == 'ACTIVE',
            AllegroOffer.price > 0
        ).order_by(func.random()).limit(120).all()

        by_cat = {}
        for o in offers:
            t = (o.title or '').lower()
            cat = 'inne'
            if 'szelki' in t:
                cat = 'szelki'
            elif 'smycz' in t:
                cat = 'smycz'
            elif 'pas' in t and ('bezp' in t or 'samoch' in t):
                cat = 'pas'
            elif 'obroz' in t:
                cat = 'obroza'
            elif 'kamizelka' in t:
                cat = 'kamizelka'
            elif 'plecak' in t:
                cat = 'plecak'
            elif 'miska' in t:
                cat = 'miska'
            elif 'zabawka' in t:
                cat = 'zabawka'
            elif 'lezak' in t or 'legowisko' in t:
                cat = 'legowisko'

            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(o)

        selected = []
        priority = ['szelki', 'smycz', 'pas', 'obroza', 'kamizelka', 'plecak', 'miska', 'zabawka', 'legowisko', 'inne']
        for cat in priority:
            if cat in by_cat and by_cat[cat]:
                o = by_cat[cat][0]
                selected.append((cat, o))

        # Dopelnij z inne jesli < 10
        if len(selected) < 10 and 'inne' in by_cat:
            for o in by_cat['inne'][1:]:
                selected.append(('inne2', o))
                if len(selected) >= 10:
                    break

        print(f"Wybrano {len(selected)} ofert:")
        print("-" * 110)
        for cat, o in selected:
            print(f"{o.offer_id}|{float(o.price):.2f}|{cat}|{o.title[:80]}")
