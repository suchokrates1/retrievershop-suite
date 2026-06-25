#!/usr/bin/env python3
from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.price_reports import PriceReportItem

SAMPLES = ["18675226204", "18595218828", "18661454079", "18658765995"]


def main() -> None:
    app = create_app()
    with app.app_context():
        with get_session() as s:
            for oid in SAMPLES:
                r113 = s.query(PriceReportItem).filter_by(report_id=113, offer_id=oid).first()
                r114 = s.query(PriceReportItem).filter_by(report_id=114, offer_id=oid).first()
                print(f"\n{oid}:")
                if r113:
                    print(f"  #113 our={r113.our_price} comp={r113.competitor_price} cheapest={r113.is_cheapest}")
                if r114:
                    print(f"  #114 our={r114.our_price} comp={r114.competitor_price} cheapest={r114.is_cheapest}")
                elif r113:
                    print("  #114: jeszcze nie sprawdzono")


if __name__ == "__main__":
    main()
