from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from magazyn.services.allegro_ads_panel.client import AllegroAdsPanelClient


def _chart_response() -> dict:
    return {
        "chart": [
            {
                "period": {"startDate": "2026-06-10", "endDate": "2026-06-10"},
                "values": {
                    "views": 1200,
                    "clicks": 15,
                    "cost": "18.50",
                    "totalAttributionCount": 2,
                    "totalAttributionValue": "150.00",
                    "ctr": "1.2500",
                    "cpc": "1.23",
                    "roi": "8.11",
                },
            }
        ]
    }


def test_fetch_chart_omits_marketplace_header():
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = _chart_response()
    session.post.return_value = response

    client = AllegroAdsPanelClient(session)
    client.fetch_chart(
        "NDc0MjA3MjAA",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 26),
    )

    headers = session.post.call_args.kwargs["headers"]
    assert "X-PPC-OPERATING-MARKETPLACE" not in headers
    assert headers["Accept"] == "application/json"


def test_fetch_chart_parses_non_zero_values():
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = _chart_response()
    session.post.return_value = response

    client = AllegroAdsPanelClient(session)
    points = client.fetch_chart(
        "NDc0MjA3MjAA",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 26),
    )

    assert len(points) == 1
    assert points[0].day == date(2026, 6, 10)
    assert points[0].clicks == 15
    assert points[0].impressions == 1200
    assert points[0].cost == Decimal("18.50")
    assert points[0].sale_count == 2
    assert points[0].sale_value == Decimal("150.00")
