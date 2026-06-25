#!/usr/bin/env python3
"""Reset raportu cenowego i wyczyść wszystkie pozycje."""
from __future__ import annotations

import sys

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.price_reports import PriceReport, PriceReportItem


def main() -> None:
    report_id = int(sys.argv[1]) if len(sys.argv) > 1 else 114
    app = create_app()
    with app.app_context():
        with get_session() as s:
            deleted = (
                s.query(PriceReportItem)
                .filter(PriceReportItem.report_id == report_id)
                .delete(synchronize_session=False)
            )
            report = s.query(PriceReport).filter_by(id=report_id).first()
            if not report:
                print(f"Brak raportu #{report_id}")
                return
            report.items_checked = 0
            report.status = "pending"
            s.commit()
            print(f"OK: zresetowano #{report_id}, usunieto {deleted} pozycji")


if __name__ == "__main__":
    main()
