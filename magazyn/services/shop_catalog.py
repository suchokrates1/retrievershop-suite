"""Publiczne dane katalogowe dla homepage Woo (bestsellery / ostatnia dostawa)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func

from ..db import get_session
from ..models.orders import Order, OrderProduct
from ..models.products import Product, ProductSize, PurchaseBatch

logger = logging.getLogger(__name__)


def _product_payload(product: Product, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "product_id": product.id,
        "woo_product_id": product.woo_product_id,
        "name": product.name,
        "brand": product.brand,
        "series": product.series,
        "color": product.color,
        "category": product.category,
    }
    if extra:
        row.update(extra)
    return row


def get_shop_bestsellers(*, limit: int = 8, days: int = 90) -> dict[str, Any]:
    """Top produkty (po product_id) wg sprzedanej ilości z zamówień magazynu."""
    limit = max(1, min(int(limit), 24))
    days = max(7, min(int(days), 366))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_ts = int(since.timestamp())

    with get_session() as db:
        # Grupuj po woo_product_id — kolory magazynowe mapują się na ten sam parent Woo.
        rows = (
            db.query(
                Product.woo_product_id,
                func.min(Product.id).label("product_id"),
                func.min(Product.name).label("name"),
                func.min(Product.brand).label("brand"),
                func.min(Product.series).label("series"),
                func.min(Product.category).label("category"),
                func.sum(OrderProduct.quantity).label("qty"),
                func.sum(OrderProduct.price_brutto * OrderProduct.quantity).label("revenue"),
            )
            .join(ProductSize, ProductSize.id == OrderProduct.product_size_id)
            .join(Product, Product.id == ProductSize.product_id)
            .join(Order, Order.order_id == OrderProduct.order_id)
            .filter(
                OrderProduct.product_size_id.isnot(None),
                Product.woo_product_id.isnot(None),
                Order.date_add >= since_ts,
            )
            .group_by(Product.woo_product_id)
            .order_by(func.sum(OrderProduct.quantity).desc())
            .limit(limit)
            .all()
        )

        items = []
        for r in rows:
            items.append(
                {
                    "product_id": int(r.product_id),
                    "woo_product_id": int(r.woo_product_id),
                    "name": r.name,
                    "brand": r.brand,
                    "series": r.series,
                    "category": r.category,
                    "quantity": int(r.qty or 0),
                    "revenue": float(r.revenue or 0),
                }
            )

    return {
        "ok": True,
        "type": "bestsellers",
        "days": days,
        "count": len(items),
        "items": items,
    }


def get_shop_latest_delivery(*, limit: int = 12) -> dict[str, Any]:
    """Nowości: unikalne parenty Woo z kolejnych dostaw (od najnowszej wstecz)."""
    limit = max(1, min(int(limit), 24))

    with get_session() as db:
        dates = [
            d
            for (d,) in (
                db.query(PurchaseBatch.purchase_date)
                .filter(PurchaseBatch.quantity > 0)
                .group_by(PurchaseBatch.purchase_date)
                .order_by(PurchaseBatch.purchase_date.desc())
                .limit(12)
                .all()
            )
        ]
        if not dates:
            return {
                "ok": True,
                "type": "latest_delivery",
                "purchase_date": None,
                "dates": [],
                "count": 0,
                "items": [],
            }

        latest_date = dates[0]
        use_dates: list[str] = []
        ordered: list[tuple[Product, str]] = []
        seen_woo: set[int] = set()

        for purchase_date in dates:
            rows = (
                db.query(Product, PurchaseBatch.purchase_date)
                .join(PurchaseBatch, PurchaseBatch.product_id == Product.id)
                .filter(
                    PurchaseBatch.purchase_date == purchase_date,
                    PurchaseBatch.quantity > 0,
                    Product.woo_product_id.isnot(None),
                )
                .order_by(Product.name.asc())
                .all()
            )
            added_from_date = False
            for product, pdate in rows:
                woo_id = int(product.woo_product_id)
                if woo_id in seen_woo:
                    continue
                seen_woo.add(woo_id)
                ordered.append((product, str(pdate)))
                added_from_date = True
                if len(ordered) >= limit:
                    break
            if added_from_date:
                use_dates.append(str(purchase_date))
            if len(ordered) >= limit:
                break

        items = [
            _product_payload(product, extra={"purchase_date": pdate})
            for product, pdate in ordered[:limit]
        ]

    return {
        "ok": True,
        "type": "latest_delivery",
        "purchase_date": latest_date,
        "dates": use_dates,
        "count": len(items),
        "items": items,
    }
