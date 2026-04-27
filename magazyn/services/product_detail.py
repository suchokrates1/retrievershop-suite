"""Kontekst widoku szczegolow produktu i lazy loading historii."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, or_

from ..db import get_session
from ..models.allegro import AllegroOffer
from ..models.orders import OrderProduct
from ..models.products import Product, PurchaseBatch

SIZE_ORDER = {"S": 1, "M": 2, "L": 3, "XL": 4, "2XL": 5}
MAX_HISTORY_LIMIT = 200
DEFAULT_ORDER_HISTORY_LIMIT = 50
DEFAULT_DELIVERY_HISTORY_LIMIT = 100


def build_product_history_payload(
    product_id: int,
    *,
    history_type: str = "orders",
    offset: int = 0,
    limit: int = 50,
) -> tuple[dict[str, Any], int]:
    """Zbuduj odpowiedz JSON historii zamowien albo dostaw produktu."""
    limit = min(max(limit, 1), MAX_HISTORY_LIMIT)
    offset = max(offset, 0)

    with get_session() as db:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return {"error": "not_found"}, 404

        if history_type == "deliveries":
            return _delivery_history_payload(db, product_id, offset, limit), 200

        return _order_history_payload(db, product, offset, limit), 200


def build_product_detail_context(product_id: int) -> dict[str, Any] | None:
    """Zbuduj pelny kontekst readonly widoku produktu."""
    with get_session() as db:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None

        sorted_sizes = sorted(product.sizes, key=lambda ps: SIZE_ORDER.get(ps.size, 99))
        sizes_data = _build_sizes_data(db, product_id, sorted_sizes)

        order_history, total_sold = _build_recent_order_history(
            db,
            sorted_sizes,
            limit=DEFAULT_ORDER_HISTORY_LIMIT,
        )
        deliveries = _build_delivery_history(db, product_id, limit=DEFAULT_DELIVERY_HISTORY_LIMIT)
        avg_purchase_price = _average_purchase_price(db, product_id)
        allegro_data = _build_allegro_data(db, product_id, sizes_data)

        return {
            "product": product,
            "sizes": sizes_data,
            "order_history": order_history,
            "delivery_history": deliveries,
            "total_in_stock": sum(size["quantity"] for size in sizes_data),
            "total_sold": total_sold,
            "total_delivered": sum(delivery["quantity"] for delivery in deliveries),
            "avg_purchase_price": avg_purchase_price,
            "allegro_offers": allegro_data,
        }


def _delivery_history_payload(db, product_id: int, offset: int, limit: int) -> dict[str, Any]:
    total = (
        db.query(func.count(PurchaseBatch.id))
        .filter(PurchaseBatch.product_id == product_id)
        .scalar()
        or 0
    )
    batches = (
        db.query(PurchaseBatch)
        .filter(PurchaseBatch.product_id == product_id)
        .order_by(desc(PurchaseBatch.purchase_date))
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        {
            "size": batch.size,
            "quantity": batch.quantity,
            "remaining": _remaining_quantity(batch),
            "price": float(batch.price),
            "total_value": float(batch.quantity * batch.price),
            "date": _format_purchase_date(batch.purchase_date),
            "invoice_number": batch.invoice_number,
            "supplier": batch.supplier,
        }
        for batch in batches
    ]
    return {"items": items, "total": total, "offset": offset, "has_more": offset + limit < total}


def _order_history_payload(db, product: Product, offset: int, limit: int) -> dict[str, Any]:
    sorted_sizes = sorted(product.sizes, key=lambda ps: SIZE_ORDER.get(ps.size, 99))
    filters, size_map_by_id, size_map_by_ean = _order_product_filters(sorted_sizes)
    if not filters:
        return {"items": [], "total": 0, "offset": offset, "has_more": False}

    total = db.query(func.count(OrderProduct.id)).filter(or_(*filters)).scalar() or 0
    order_products = (
        db.query(OrderProduct)
        .filter(or_(*filters))
        .order_by(desc(OrderProduct.id))
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = [
        _order_product_payload(order_product, size_map_by_id, size_map_by_ean)
        for order_product in order_products
        if order_product.order
    ]
    return {"items": items, "total": total, "offset": offset, "has_more": offset + limit < total}


def _build_sizes_data(db, product_id: int, sorted_sizes) -> list[dict[str, Any]]:
    sizes_data = []
    for product_size in sorted_sizes:
        batches = (
            db.query(PurchaseBatch)
            .filter(
                PurchaseBatch.product_id == product_id,
                PurchaseBatch.size == product_size.size,
            )
            .all()
        )
        latest_batch = _latest_purchase_batch(batches)
        total_qty = sum(batch.quantity for batch in batches)
        total_value = sum(batch.quantity * batch.price for batch in batches)
        avg_price = (total_value / total_qty) if total_qty > 0 else None

        remaining_batches = [batch for batch in batches if (batch.remaining_quantity or 0) > 0]
        fifo_remaining = sum(batch.remaining_quantity or 0 for batch in remaining_batches)

        sizes_data.append(
            {
                "id": product_size.id,
                "size": product_size.size,
                "quantity": product_size.quantity,
                "fifo_remaining": fifo_remaining,
                "barcode": product_size.barcode,
                "purchase_price": latest_batch.price if latest_batch else None,
                "avg_purchase_price": avg_price,
            }
        )
    return sizes_data


def _build_recent_order_history(db, sorted_sizes, *, limit: int) -> tuple[list[dict[str, Any]], int]:
    filters, size_map_by_id, size_map_by_ean = _order_product_filters(sorted_sizes)
    if not filters:
        return [], 0

    total_sold = (
        db.query(func.coalesce(func.sum(OrderProduct.quantity), 0))
        .filter(or_(*filters))
        .scalar()
        or 0
    )
    order_products = (
        db.query(OrderProduct)
        .filter(or_(*filters))
        .order_by(desc(OrderProduct.id))
        .limit(limit)
        .all()
    )
    return [
        _order_product_detail(order_product, size_map_by_id, size_map_by_ean)
        for order_product in order_products
        if order_product.order
    ], total_sold


def _build_delivery_history(db, product_id: int, *, limit: int) -> list[dict[str, Any]]:
    batches = (
        db.query(PurchaseBatch)
        .filter(PurchaseBatch.product_id == product_id)
        .order_by(desc(PurchaseBatch.purchase_date))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": batch.id,
            "size": batch.size,
            "quantity": batch.quantity,
            "remaining": _remaining_quantity(batch),
            "price": batch.price,
            "total_value": batch.quantity * batch.price,
            "date": batch.purchase_date,
            "barcode": batch.barcode,
            "invoice_number": batch.invoice_number,
            "supplier": batch.supplier,
        }
        for batch in batches
    ]


def _average_purchase_price(db, product_id: int) -> Decimal | None:
    batches = db.query(PurchaseBatch).filter(PurchaseBatch.product_id == product_id).all()
    total_qty = sum(batch.quantity for batch in batches)
    total_value = sum(batch.quantity * batch.price for batch in batches)
    return (total_value / total_qty) if total_qty > 0 else None


def _build_allegro_data(db, product_id: int, sizes_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    size_ids = [size["id"] for size in sizes_data]
    allegro_offers = (
        db.query(AllegroOffer)
        .filter(
            (AllegroOffer.product_id == product_id)
            | (AllegroOffer.product_size_id.in_(size_ids))
        )
        .order_by(AllegroOffer.title)
        .all()
    )

    return [
        {
            "offer_id": offer.offer_id,
            "title": offer.title,
            "price": offer.price,
            "ean": offer.ean,
            "matched_size": _matched_allegro_size(offer, sizes_data),
            "publication_status": offer.publication_status,
        }
        for offer in allegro_offers
    ]


def _order_product_filters(sorted_sizes) -> tuple[list[Any], dict[int, str], dict[str, str]]:
    size_ids = [product_size.id for product_size in sorted_sizes]
    eans = [product_size.barcode for product_size in sorted_sizes if product_size.barcode]
    size_map_by_id = {product_size.id: product_size.size for product_size in sorted_sizes}
    size_map_by_ean = {
        product_size.barcode: product_size.size
        for product_size in sorted_sizes
        if product_size.barcode
    }

    filters = []
    if size_ids:
        filters.append(OrderProduct.product_size_id.in_(size_ids))
    if eans:
        filters.append(OrderProduct.ean.in_(eans))

    return filters, size_map_by_id, size_map_by_ean


def _order_product_payload(
    order_product: OrderProduct,
    size_map_by_id: dict[int, str],
    size_map_by_ean: dict[str, str],
) -> dict[str, Any]:
    order = order_product.order
    return {
        "order_id": order_product.order_id,
        "lp": order.lp if getattr(order, "lp", None) else order_product.order_id,
        "date": order.date_add,
        "customer": order.customer_name,
        "quantity": order_product.quantity,
        "price": float(order_product.price_brutto) if order_product.price_brutto else None,
        "size": _order_product_size(order_product, size_map_by_id, size_map_by_ean),
    }


def _order_product_detail(
    order_product: OrderProduct,
    size_map_by_id: dict[int, str],
    size_map_by_ean: dict[str, str],
) -> dict[str, Any]:
    order = order_product.order
    return {
        "order_id": order_product.order_id,
        "lp": order.lp if getattr(order, "lp", None) else order_product.order_id,
        "external_order_id": order.external_order_id,
        "date": order.date_add,
        "customer": order.customer_name,
        "platform": order.platform,
        "quantity": order_product.quantity,
        "price": order_product.price_brutto,
        "ean": order_product.ean,
        "size": _order_product_size(order_product, size_map_by_id, size_map_by_ean),
    }


def _order_product_size(
    order_product: OrderProduct,
    size_map_by_id: dict[int, str],
    size_map_by_ean: dict[str, str],
) -> str | None:
    if order_product.product_size_id and order_product.product_size_id in size_map_by_id:
        return size_map_by_id[order_product.product_size_id]
    if order_product.ean and order_product.ean in size_map_by_ean:
        return size_map_by_ean[order_product.ean]
    return None


def _matched_allegro_size(offer: AllegroOffer, sizes_data: list[dict[str, Any]]) -> str | None:
    if not offer.product_size_id:
        return None
    return next(
        (size["size"] for size in sizes_data if size["id"] == offer.product_size_id),
        None,
    )


def _remaining_quantity(batch: PurchaseBatch) -> int:
    return batch.remaining_quantity if batch.remaining_quantity is not None else batch.quantity


def _format_purchase_date(value) -> str | None:
    if not value:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _latest_purchase_batch(batches: list[PurchaseBatch]) -> PurchaseBatch | None:
    latest = None
    for batch in batches:
        if latest is None:
            latest = batch
        elif batch.purchase_date and (
            not latest.purchase_date or batch.purchase_date > latest.purchase_date
        ):
            latest = batch
    return latest


__all__ = ["build_product_detail_context", "build_product_history_payload"]