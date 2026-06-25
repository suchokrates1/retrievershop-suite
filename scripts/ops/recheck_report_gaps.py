#!/usr/bin/env python3
"""Usuwa niekompletne wpisy raportu #114 i wznawia sprawdzanie brakujacych ofert."""

from __future__ import annotations

import sys

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.allegro import AllegroOffer
from magazyn.models.price_reports import PriceReport, PriceReportItem
from magazyn.price_report_scheduler import resume_price_report
from magazyn.services.price_report_processing import count_checked_offers

REPORT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 114


def main() -> None:
    app = create_app()
    with app.app_context():
        with get_session() as s:
            report = s.query(PriceReport).filter_by(id=REPORT_ID).first()
            if not report:
                print(f"Brak raportu #{REPORT_ID}")
                return

            # Nieudane scrapy (error) — restart_price_report to robi, ale na wszelki wypadek:
            err_items = (
                s.query(PriceReportItem)
                .filter(
                    PriceReportItem.report_id == REPORT_ID,
                    PriceReportItem.error.isnot(None),
                )
                .all()
            )
            for item in err_items:
                s.delete(item)
            print(f"usunieto_bledy={len(err_items)}")

            # Scrap bez konkurenta, ale z proba (total_offers ustawione) — do ponownego sprawdzenia
            incomplete = (
                s.query(PriceReportItem)
                .filter(
                    PriceReportItem.report_id == REPORT_ID,
                    PriceReportItem.competitor_price.is_(None),
                    PriceReportItem.total_offers.isnot(None),
                )
                .all()
            )
            for item in incomplete:
                s.delete(item)
            print(f"usunieto_niekompletne={len(incomplete)}")

            # Aktywne oferty bez wpisu w raporcie
            checked_ids = {
                row[0]
                for row in s.query(PriceReportItem.offer_id)
                .filter_by(report_id=REPORT_ID)
                .all()
            }
            active_ids = {
                row[0]
                for row in s.query(AllegroOffer.offer_id)
                .filter(AllegroOffer.publication_status == "ACTIVE")
                .all()
            }
            missing = sorted(active_ids - checked_ids)
            print(f"brakujace_oferty={len(missing)}")

            report.items_checked = count_checked_offers(s, REPORT_ID)
            report.status = "running"
            s.commit()
            print(f"items_checked_po_sync={report.items_checked}/{report.items_total}")

        result = resume_price_report(REPORT_ID)
        print(f"OK: wznowiono raport #{result}")


if __name__ == "__main__":
    main()
