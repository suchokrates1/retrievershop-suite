"""Diagnostyka Cordura - dlaczego Inna OK przy 1 ofercie na ps_id."""
from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import AllegroOffer, PriceReportItem, PriceReport

app = create_app()
with app.app_context():
    with get_session() as s:
        # Najnowszy raport
        report = s.query(PriceReport).order_by(PriceReport.id.desc()).first()
        print(f"Raport #{report.id}: status={report.status}, {report.items_checked}/{report.items_total}")

        items = s.query(PriceReportItem).filter(PriceReportItem.report_id == report.id).all()
        inna_ok = [i for i in items if not i.is_cheapest and i.competitor_price is None and i.error is None]

        active = s.query(AllegroOffer).filter(AllegroOffer.publication_status == "ACTIVE").all()
        ps_groups = {}
        for o in active:
            ps_groups.setdefault(o.product_size_id, []).append(o)

        # Znajdz Cordura
        cordura = [o for o in active if o.title and "cordura" in o.title.lower()]
        print(f"\nOferty Cordura (aktywne): {len(cordura)}")
        checked_ids = set(i.offer_id for i in items)
        for o in cordura:
            grp = ps_groups.get(o.product_size_id, [])
            item = next((i for i in items if i.offer_id == o.offer_id), None)
            status = "brak w raporcie"
            if item:
                if item.error:
                    status = f"BLAD: {item.error}"
                elif item.competitor_price is None and not item.is_cheapest:
                    status = "!! Inna OK"
                elif item.is_cheapest:
                    status = f"Najtanszy (vs {item.competitor_price})"
                else:
                    status = f"Drozszy (vs {item.competitor_price})"
            print(f"  {o.offer_id} ps={o.product_size_id} pid={o.product_id} "
                  f"cena={o.price} aktywne_na_ps={len(grp)} -> {status}")

        # Wszystkie bledne Inna OK (jedyna oferta na ps_id)
        print(f"\n--- WSZYSTKIE BLEDNE INNA OK (jedyna aktywna na ps_id) ---")
        cnt = 0
        for item in inna_ok:
            offer = next((o for o in active if o.offer_id == item.offer_id), None)
            if offer:
                grp = len(ps_groups.get(offer.product_size_id, []))
                if grp == 1:
                    cnt += 1
                    print(f"  {item.offer_id} ps={offer.product_size_id} pid={offer.product_id} "
                          f"{item.our_price}zl {(offer.title or '')[:60]}")
        print(f"Lacznie blednych: {cnt}")

        # Sprawdz skad pochodzi Inna OK - mark_sibling_offers czy CDP
        # mark_sibling grupuje po product_size_id - nie powinno dotyczyc single-ps
        # CDP grupuje po dialogu - moze dotyczyc roznych ps_id
        # Sprawdz checked_at - jesli None, to z mark_sibling (preprocess)
        print(f"\n--- ZRODLO BLEDNYCH ---")
        for item in inna_ok:
            offer = next((o for o in active if o.offer_id == item.offer_id), None)
            if offer:
                grp = len(ps_groups.get(offer.product_size_id, []))
                if grp == 1:
                    # Czy checked_at jest null?
                    print(f"  {item.offer_id}: checked_at={item.checked_at}, "
                          f"our_position={item.our_position}, total_offers={item.total_offers}")
