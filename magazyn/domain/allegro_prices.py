"""Domain helpers for Allegro price history management and reporting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AllegroPriceHistory

TWOPLACES = Decimal("0.01")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(TWOPLACES)
    return Decimal(value).quantize(TWOPLACES)


def record_price_point(
    session: Session,
    *,
    offer_id: Optional[str],
    product_size_id: Optional[int],
    price,
    recorded_at: Optional[datetime | str] = None,
) -> None:
    """Persist a new price history sample."""

    if recorded_at is None:
        recorded_at = _now()
    if isinstance(recorded_at, datetime):
        recorded_at = recorded_at.astimezone(timezone.utc).isoformat()

    price_value = _to_decimal(price)

    session.add(
        AllegroPriceHistory(
            offer_id=offer_id,
            product_size_id=product_size_id,
            price=price_value,
            recorded_at=recorded_at,
        )
    )


def generate_trend_report(
    session: Session,
    *,
    window_hours: int = 24,
    offer_prefix: Optional[str] = None,
) -> list[dict]:
    """Return aggregated price trends for the requested time window."""

    window_start = _now() - timedelta(hours=window_hours)
    query = session.query(
        AllegroPriceHistory.offer_id,
        AllegroPriceHistory.product_size_id,
        func.min(AllegroPriceHistory.price),
        func.max(AllegroPriceHistory.price),
        func.count(AllegroPriceHistory.id),
    ).filter(AllegroPriceHistory.recorded_at >= window_start.isoformat())

    if offer_prefix is not None:
        like_pattern = f"{offer_prefix}%"
        query = query.filter(AllegroPriceHistory.offer_id.like(like_pattern))

    rows: Iterable[tuple[str | None, int | None, Decimal, Decimal, int]] = (
        query.group_by(
            AllegroPriceHistory.offer_id, AllegroPriceHistory.product_size_id
        ).all()
    )

    trends: list[dict] = []
    for offer_id, product_size_id, min_price, max_price, count in rows:
        if min_price is None or max_price is None:
            continue
        min_price = _to_decimal(min_price)
        max_price = _to_decimal(max_price)
        change = (max_price - min_price).quantize(TWOPLACES)
        trends.append(
            {
                "offer_id": offer_id,
                "product_size_id": product_size_id,
                "min_price": min_price,
                "max_price": max_price,
                "change": change,
                "samples": int(count or 0),
            }
        )

    trends.sort(
        key=lambda item: (abs(item["change"]), item["offer_id"] or ""), reverse=True
    )
    return trends


__all__ = ["record_price_point", "generate_trend_report"]
