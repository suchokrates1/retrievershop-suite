#!/usr/bin/env python3
from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.price_reports import PriceReport, PriceReportItem


def main() -> None:
    app = create_app()
    with app.app_context():
        with get_session() as s:
            for rid in (113, 114):
                r = s.query(PriceReport).filter_by(id=rid).first()
                if not r:
                    print(f"#{rid}: brak")
                    continue
                items = s.query(PriceReportItem).filter_by(report_id=rid).count()
                cheapest = (
                    s.query(PriceReportItem)
                    .filter_by(report_id=rid, is_cheapest=True)
                    .count()
                )
                not_cheapest = (
                    s.query(PriceReportItem)
                    .filter_by(report_id=rid, is_cheapest=False)
                    .filter(PriceReportItem.error.is_(None))
                    .count()
                )
                print(
                    f"#{rid} status={r.status} checked={r.items_checked}/{r.items_total} "
                    f"items={items} cheapest={cheapest} drozsze={not_cheapest}"
                )


if __name__ == "__main__":
    main()
