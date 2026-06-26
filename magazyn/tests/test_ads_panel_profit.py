from datetime import date
from decimal import Decimal

from magazyn.db import get_session
from magazyn.models.orders import Order, OrderProduct
from magazyn.services.allegro_ads_panel.profit import compute_profit_by_offer
from magazyn.services.stats_api_ads_panel import _charts_by_campaign, _sold_item_metrics


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


def test_charts_by_campaign_groups_points():
    points = [
        type("P", (), {"campaign_entity_id": "", "day": date(2026, 6, 1), "clicks": 1, "impressions": 2, "cost": Decimal("1"), "sale_count": 0, "sale_value": Decimal("0"), "ctr": None, "cpc": None, "roi": None})(),
        type("P", (), {"campaign_entity_id": "camp-a", "day": date(2026, 6, 1), "clicks": 3, "impressions": 4, "cost": Decimal("2"), "sale_count": 1, "sale_value": Decimal("10"), "ctr": None, "cpc": None, "roi": None})(),
    ]
    grouped = _charts_by_campaign(points)
    assert len(grouped[""]) == 1
    assert len(grouped["camp-a"]) == 1
    assert grouped["camp-a"][0]["clicks"] == 3


def test_sold_item_metrics_per_unit():
    item = type("Item", (), {"offer_id": "1", "offer_name": "Test", "quantity": 4, "sale_value": Decimal("400")})()
    metrics = _sold_item_metrics(
        item=item,
        campaign_cost=Decimal("100"),
        campaign_sale_value=Decimal("400"),
        offer_profit={"real_profit": Decimal("80"), "real_revenue": Decimal("400"), "orders": 2},
    )
    assert metrics["ad_cost"] == 100.0
    assert metrics["ad_cost_per_unit"] == 25.0
    assert metrics["net_profit"] == -20.0
    assert metrics["net_profit_per_unit"] == -5.0
