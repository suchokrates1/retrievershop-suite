"""Diagnostyka raportu #51."""
from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import AllegroOffer, PriceReportItem, PriceReport

app = create_app()
with app.app_context():
    with get_session() as s:
        # Pokaz dostepne raporty
        all_reports = s.query(PriceReport).order_by(PriceReport.id.desc()).limit(10).all()
        print("Dostepne raporty:")
        for r in all_reports:
            print(f"  #{r.id}: status={r.status}, {r.items_checked}/{r.items_total}, {r.created_at}")

        # Sprawdz najnowszy ukonczony raport
        report = s.query(PriceReport).filter(
            PriceReport.status.in_(["completed", "completed_with_errors"])
        ).order_by(PriceReport.id.desc()).first()
        if not report:
            print("Brak ukonczonych raportow")
            exit()
        print(f"\nRaport #{report.id}: status={report.status}, total={report.items_total}, "
              f"checked={report.items_checked}, created={report.created_at}")

        items = s.query(PriceReportItem).filter(PriceReportItem.report_id == report.id).all()
        inna_ok = [i for i in items if not i.is_cheapest and i.competitor_price is None and i.error is None]
        errors = [i for i in items if i.error is not None]
        checked = [i for i in items if (i.competitor_price is not None or i.is_cheapest) and i.error is None]
        print(f"Pozycje: {len(items)}, sprawdzone={len(checked)}, inna_ok={len(inna_ok)}, bledy={len(errors)}")

        active = s.query(AllegroOffer).filter(AllegroOffer.publication_status == "ACTIVE").all()
        checked_ids = set(i.offer_id for i in items)
        missing = [o for o in active if o.offer_id not in checked_ids]
        print(f"Aktywne oferty: {len(active)}, w raporcie: {len(checked_ids)}, BRAKUJACE: {len(missing)}")

        if missing:
            print("\nBrakujace oferty (nie sa w raporcie):")
            for o in missing:
                print(f"  {o.offer_id} pid={o.product_id} ps={o.product_size_id} "
                      f"{o.price}zl {(o.title or '')[:55]}")

        # Grupuj aktywne po product_size_id
        ps_groups = {}
        for o in active:
            ps_groups.setdefault(o.product_size_id, []).append(o)

        # Inna OK ale jedyna oferta na ps_id = blad
        print(f"\nInna OK blednie oznaczone (jedyna aktywna oferta na ps_id):")
        cnt = 0
        for item in inna_ok:
            offer = next((o for o in active if o.offer_id == item.offer_id), None)
            if offer:
                grp = len(ps_groups.get(offer.product_size_id, []))
                if grp == 1:
                    cnt += 1
                    print(f"  !! {item.offer_id} ps={offer.product_size_id} pid={offer.product_id} "
                          f"{item.our_price}zl {(offer.title or '')[:55]}")
        print(f"Lacznie blednych Inna OK: {cnt}")

        # Pokaz tez poprawne Inna OK dla kontekstu
        print(f"\nPoprawne Inna OK (sa siostry na tym samym ps_id): {len(inna_ok) - cnt}")
