from __future__ import annotations

from datetime import datetime, timedelta, timezone

import magazyn.config as cfg
from magazyn.db import sqlite_connect
from magazyn.models import Product, ProductSize, Sale, AllegroPriceHistory


def _explain(sql: str, *params: object) -> list[str]:
    with sqlite_connect(cfg.settings.DB_PATH) as conn:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    return [row[-1] for row in rows]


def test_allegro_sync_query_uses_product_size_index(app_mod):
    with app_mod.get_session() as db:
        product = Product(name="Speedy", color="Blue")
        db.add(product)
        db.flush()
        db.add_all(
            [
                ProductSize(product_id=product.id, size="M", quantity=3),
                ProductSize(product_id=product.id, size="L", quantity=1),
            ]
        )

    plan = _explain(
        """
        SELECT ps.id
        FROM product_sizes AS ps
        JOIN products AS p ON p.id = ps.product_id
        WHERE p.name = ? AND ps.size = ?
        """,
        "Speedy",
        "M",
    )

    assert any("idx_product_sizes_product_id_size" in line for line in plan)


def test_sales_summary_filters_use_sale_date_index(app_mod):
    now = datetime.now(timezone.utc)
    with app_mod.get_session() as db:
        product = Product(name="Widget", color="Red")
        db.add(product)
        db.flush()
        db.add_all(
            [
                Sale(
                    product_id=product.id,
                    size="M",
                    quantity=1,
                    sale_date=(now - timedelta(days=1)).isoformat(),
                ),
                Sale(
                    product_id=product.id,
                    size="L",
                    quantity=2,
                    sale_date=(now - timedelta(days=2)).isoformat(),
                ),
            ]
        )

    plan = _explain(
        """
        SELECT s.product_id, s.size, SUM(s.quantity)
        FROM sales AS s
        WHERE s.sale_date >= ?
        GROUP BY s.product_id, s.size
        """,
        (now - timedelta(days=7)).isoformat(),
    )

    assert any("idx_sales_sale_date" in line for line in plan)


def test_price_history_window_uses_recorded_at_index(app_mod):
    now = datetime.now(timezone.utc)
    earlier = (now - timedelta(hours=1)).isoformat()
    with app_mod.get_session() as db:
        db.add_all(
            [
                AllegroPriceHistory(
                    offer_id="A1",
                    product_size_id=None,
                    price=10,
                    recorded_at=earlier,
                ),
                AllegroPriceHistory(
                    offer_id="A1",
                    product_size_id=None,
                    price=11,
                    recorded_at=now.isoformat(),
                ),
            ]
        )

    plan = _explain(
        """
        SELECT offer_id, MIN(price), MAX(price)
        FROM allegro_price_history
        WHERE recorded_at >= ?
        GROUP BY offer_id
        """,
        (now - timedelta(hours=2)).isoformat(),
    )

    expected = {
        "idx_allegro_price_history_recorded_at",
        "idx_allegro_price_history_offer_recorded_at",
        "ix_allegro_price_history_offer_id",
    }
    assert any(any(name in line for name in expected) for line in plan)
