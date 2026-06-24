from datetime import date
from decimal import Decimal

from magazyn.db import get_session
from magazyn.models.orders import Order, OrderProduct
from magazyn.services.allegro_ads_panel.profit import compute_profit_by_offer


def test_compute_profit_by_offer_splits_order_profit(app):
    with get_session() as db:
        db.add(
            Order(
                order_id="ADS-1",
                platform="allegro",
                date_add=1_700_000_000,
                payment_done=Decimal("200.00"),
                real_profit_amount=Decimal("50.00"),
            )
        )
        db.add(
            OrderProduct(
                order_id="ADS-1",
                auction_id="111",
                quantity=1,
                price_brutto=Decimal("100.00"),
            )
        )
        db.add(
            OrderProduct(
                order_id="ADS-1",
                auction_id="222",
                quantity=1,
                price_brutto=Decimal("100.00"),
            )
        )
        db.commit()

        result = compute_profit_by_offer(
            db,
            period_start=date(2023, 11, 14),
            period_end=date(2023, 11, 15),
            offer_ids={"111"},
        )

    assert result["111"]["real_profit"] == Decimal("25.00")
    assert result["111"]["real_revenue"] == Decimal("100.00")
    assert result["111"]["orders"] == 1
