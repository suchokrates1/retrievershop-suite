from __future__ import annotations

from datetime import datetime
from typing import List

import pandas as pd
from sqlalchemy import func

from ..db import get_session
from ..models import Product, ProductSize, Sale


def get_sales_summary(days: int = 7) -> List[dict]:
    """Return sales summary for the given period."""
    start = datetime.now() - pd.Timedelta(days=days)
    with get_session() as db:
        stock = {
            (product_id, size): quantity
            for product_id, size, quantity in (
                db.query(
                    ProductSize.product_id,
                    ProductSize.size,
                    ProductSize.quantity,
                ).all()
            )
        }
        rows = (
            db.query(
                Product.id,
                Product.name,
                Product.color,
                Sale.size,
                func.sum(Sale.quantity).label("qty"),
            )
            .join(Product, Sale.product_id == Product.id)
            .filter(Sale.sale_date >= start.isoformat())
            .group_by(Sale.product_id, Sale.size)
            .all()
        )

        summary = []
        for product_id, name, color, size, qty in rows:
            remaining = stock.get((product_id, size), 0)
            summary.append(
                {
                    "name": name,
                    "color": color,
                    "size": size,
                    "sold": int(qty or 0),
                    "remaining": remaining,
                }
            )

    return summary


__all__ = ["get_sales_summary"]
