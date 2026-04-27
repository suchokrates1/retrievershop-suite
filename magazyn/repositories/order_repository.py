"""Repozytorium zapytan dla zamowien."""

from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from ..models.orders import Order, OrderProduct, OrderStatusLog
from ..models.returns import Return
from ..status_config import STATUS_FILTER_GROUPS


class OrderRepository:
    """Centralizuje zapytania uzywane przez widoki i serwisy zamowien."""

    def __init__(self, db: Session):
        self.db = db

    def list_query(
        self,
        *,
        search: str,
        status_filter: str,
        date_from: str,
        date_to: str,
        sort_by: str,
        sort_dir: str,
    ):
        query = self.db.query(Order)
        query = self._apply_search(query, search)
        query = self._apply_date_range(query, date_from, date_to)
        query = self._apply_status_filter(query, status_filter)
        return self._apply_sorting(query, sort_by, sort_dir)

    def chronological_order_ids(self, *, search: str = "") -> list[str]:
        query = self.db.query(Order.order_id)
        query = self._apply_search(query, search)
        return [row.order_id for row in query.order_by(Order.date_add.asc()).all()]

    def latest_status(self, order_id: str) -> OrderStatusLog | None:
        return (
            self.db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order_id)
            .order_by(desc(OrderStatusLog.timestamp))
            .first()
        )

    def order_products(self, order_id: str) -> list[OrderProduct]:
        return self.db.query(OrderProduct).filter(OrderProduct.order_id == order_id).all()

    def active_return(self, order_id: str) -> Return | None:
        return (
            self.db.query(Return)
            .filter(Return.order_id == order_id, Return.status != "cancelled")
            .first()
        )

    def _apply_search(self, query, search: str):
        if not search:
            return query

        search_pattern = f"%{search}%"
        product_match_subq = (
            self.db.query(OrderProduct.order_id)
            .filter(OrderProduct.name.ilike(search_pattern))
            .distinct()
            .subquery()
        )
        return query.filter(
            or_(
                Order.order_id.ilike(search_pattern),
                Order.external_order_id.ilike(search_pattern),
                Order.customer_name.ilike(search_pattern),
                Order.email.ilike(search_pattern),
                Order.phone.ilike(search_pattern),
                Order.delivery_method.ilike(search_pattern),
                Order.order_id.in_(product_match_subq),
            )
        )

    @staticmethod
    def _parse_date(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None

    def _apply_date_range(self, query, date_from: str, date_to: str):
        dt_from = self._parse_date(date_from)
        if dt_from:
            query = query.filter(Order.date_add >= int(dt_from.timestamp()))

        dt_to = self._parse_date(date_to)
        if dt_to:
            query = query.filter(Order.date_add < int((dt_to + timedelta(days=1)).timestamp()))

        return query

    def _apply_status_filter(self, query, status_filter: str):
        if not status_filter or status_filter == "all":
            return query

        latest_status_subq = (
            self.db.query(
                OrderStatusLog.order_id,
                func.max(OrderStatusLog.timestamp).label("max_ts"),
            )
            .group_by(OrderStatusLog.order_id)
            .subquery()
        )
        query = query.join(
            latest_status_subq,
            Order.order_id == latest_status_subq.c.order_id,
        ).join(
            OrderStatusLog,
            (OrderStatusLog.order_id == latest_status_subq.c.order_id)
            & (OrderStatusLog.timestamp == latest_status_subq.c.max_ts),
        )

        if status_filter in STATUS_FILTER_GROUPS:
            return query.filter(OrderStatusLog.status.in_(STATUS_FILTER_GROUPS[status_filter]))
        return query.filter(OrderStatusLog.status == status_filter)

    @staticmethod
    def _apply_sorting(query, sort_by: str, sort_dir: str):
        if sort_by == "amount":
            sort_col = Order.payment_done
        else:
            sort_col = Order.date_add

        if sort_dir == "asc":
            return query.order_by(sort_col.asc())
        return query.order_by(sort_col.desc())


__all__ = ["OrderRepository"]