from datetime import date
from decimal import Decimal

from magazyn.db import get_session
from magazyn.models.orders import Order, OrderProduct
from magazyn.services.allegro_ads_panel.profit import compute_profit_by_offer
from magazyn.services.stats_api_ads_panel import (
    AGGREGATE_CAMPAIGN_NAME,
    _charts_by_campaign,
    _scale_offer_profit_to_ads_sale,
    _serialize_campaign_row,
    _sold_item_metrics,
)


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
    assert len(result["111"]["order_lines"]) == 1
    assert result["111"]["order_lines"][0]["order_id"] == "ADS-1"
    assert result["111"]["order_lines"][0]["attributed_profit"] == Decimal("25.00")


def test_scale_offer_profit_to_ads_sale_scales_when_revenues_differ():
    offer_profit = {
        "real_profit": Decimal("185.98"),
        "real_revenue": Decimal("602.00"),
        "orders": 6,
        "order_lines": [
            {
                "order_id": "o1",
                "quantity": 1,
                "line_revenue": Decimal("86.00"),
                "attributed_profit": Decimal("31.03"),
                "date_add": 1,
            },
            {
                "order_id": "o2",
                "quantity": 3,
                "line_revenue": Decimal("516.00"),
                "attributed_profit": Decimal("154.95"),
                "date_add": 2,
            },
        ],
    }
    real_profit, real_revenue, lines = _scale_offer_profit_to_ads_sale(
        ads_sale_value=Decimal("344.00"),
        offer_profit=offer_profit,
    )
    assert real_revenue == Decimal("344.00")
    assert round(float(real_profit), 2) == 106.27
    assert round(float(sum(Decimal(str(line["attributed_profit"])) for line in lines)), 2) == 106.27


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
        offer_profit={
            "real_profit": Decimal("80"),
            "real_revenue": Decimal("400"),
            "orders": 2,
            "order_lines": [],
        },
        product_id=12,
    )
    assert metrics["ad_cost"] == 100.0
    assert metrics["ad_cost_per_unit"] == 25.0
    assert metrics["net_profit"] == -20.0
    assert metrics["net_profit_per_unit"] == -5.0
    assert metrics["product_id"] == 12


def test_serialize_campaign_row_aggregate_uses_child_summary():
    detail_row = type(
        "Campaign",
        (),
        {
            "campaign_name": "Ads Express",
            "campaign_entity_id": "camp-a",
            "clicks": 10,
            "impressions": 100,
            "ctr": None,
            "cpc": None,
            "cost": Decimal("50"),
            "roi": None,
            "interest": 0,
            "sale_count": 2,
            "sale_value": Decimal("200"),
            "sold_items": [
                type(
                    "Item",
                    (),
                    {
                        "offer_id": "111",
                        "offer_name": "Produkt A",
                        "quantity": 2,
                        "sale_value": Decimal("200"),
                    },
                )()
            ],
        },
    )()
    aggregate_row = type(
        "Campaign",
        (),
        {
            "campaign_name": AGGREGATE_CAMPAIGN_NAME,
            "campaign_entity_id": "",
            "clicks": 10,
            "impressions": 100,
            "ctr": None,
            "cpc": None,
            "cost": Decimal("50"),
            "roi": None,
            "interest": 0,
            "sale_count": 2,
            "sale_value": Decimal("200"),
            "sold_items": [],
        },
    )()
    profit_by_offer = {
        "111": {
            "real_profit": Decimal("80"),
            "real_revenue": Decimal("200"),
            "orders": 1,
            "order_lines": [],
        }
    }

    detail_payload, ad_sales_items, detail_summary = _serialize_campaign_row(
        detail_row,
        profit_by_offer=profit_by_offer,
        product_by_offer={"111": 7},
        collect_ad_sales=True,
    )
    aggregate_payload, _, _ = _serialize_campaign_row(
        aggregate_row,
        profit_by_offer=profit_by_offer,
        product_by_offer={"111": 7},
        profit_summary=detail_summary,
        collect_ad_sales=False,
    )

    assert detail_payload["real_profit"] == 80.0
    assert len(ad_sales_items) == 1
    assert aggregate_payload["real_profit"] == 80.0
    assert aggregate_payload["sold_items"] == []
