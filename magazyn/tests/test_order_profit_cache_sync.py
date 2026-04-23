from decimal import Decimal

from magazyn.db import get_session
from magazyn.models import Order
from magazyn.order_sync_scheduler import _refresh_order_profit_cache
from magazyn.settings_store import settings_store


def test_refresh_order_profit_cache_persists_incomplete_allegro_order(app, monkeypatch):
    with app.app_context():
        with get_session() as db:
            order = Order(
                order_id="allegro_cache_1",
                external_order_id="ext-cache-1",
                platform="allegro",
                date_add=1,
                payment_done=Decimal("100.00"),
                delivery_method="InPost",
                payment_method_cod=False,
            )
            db.add(order)
            db.commit()

        monkeypatch.setattr(
            settings_store,
            "get",
            lambda key, default=None: "token" if key == "ALLEGRO_ACCESS_TOKEN" else default,
        )
        monkeypatch.setattr(
            "magazyn.domain.financial.FinancialCalculator._prefetch_order_billing_summaries",
            lambda self, orders, access_token, trace_label=None: {
                "ext-cache-1": {
                    "success": True,
                    "total_fees": Decimal("20.00"),
                    "total_fees_with_estimate": Decimal("28.99"),
                    "estimated_shipping": {"estimated_cost": Decimal("8.99")},
                    "entries": [{"id": "entry-1"}],
                }
            },
        )

        stats = _refresh_order_profit_cache(app)

        assert stats["checked"] == 1
        assert stats["updated"] == 1
        assert stats["pending"] == 1
        assert stats["finalized"] == 0

        with get_session() as db:
            saved = db.query(Order).filter(Order.order_id == "allegro_cache_1").first()

        assert saved.real_profit_sale_price == Decimal("100.00")
        assert saved.real_profit_allegro_fees == Decimal("28.99")
        assert saved.real_profit_amount == Decimal("70.85")
        assert saved.real_profit_shipping_estimated is True
        assert saved.real_profit_is_final is False