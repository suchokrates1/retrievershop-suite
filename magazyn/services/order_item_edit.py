"""Edycja wariantu (kolor/rozmiar) pozycji zamowienia."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from sqlalchemy import desc

from ..config import settings
from ..db import TWOPLACES, consume_stock, get_session
from ..models.orders import Order, OrderProduct, OrderStatusLog
from ..models.products import Product, ProductSize, Sale
from .order_status import add_order_status

logger = logging.getLogger(__name__)

EDIT_BLOCKED_STATUSES = frozenset({
    "anulowano",
    "dostarczono",
    "zwrot",
    "nieodebrano",
})


@dataclass(frozen=True)
class OrderItemEditResult:
    message: str
    category: str
    not_found: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def can_edit_order_items(current_status: str) -> bool:
    return current_status not in EDIT_BLOCKED_STATUSES


def _current_order_status(db, order_id: str) -> str:
    last = (
        db.query(OrderStatusLog)
        .filter(OrderStatusLog.order_id == order_id)
        .order_by(desc(OrderStatusLog.timestamp))
        .first()
    )
    return last.status if last else "pobrano"


def _product_family_key(product: Product) -> tuple:
    return (
        (product.category or "").strip().lower(),
        (product.brand or "").strip().lower(),
        (product.series or "").strip().lower(),
    )


def _format_variant_name(product: Product, size: str) -> str:
    parts = [product.name]
    if product.color:
        parts.append(product.color)
    if size:
        parts.append(size)
    return " ".join(p for p in parts if p)


def _same_family(a: Product, b: Product) -> bool:
    key_a = _product_family_key(a)
    key_b = _product_family_key(b)
    if not any(key_a) and not any(key_b):
        # Fallback: ten sam product_id (tylko zmiana rozmiaru)
        return a.id == b.id
    return key_a == key_b and any(key_a)


def _order_has_consumed_stock(db, order_id: str) -> bool:
    return db.query(Sale.id).filter(Sale.order_id == order_id).first() is not None


SWAP_MODE_VARIANT = "wariant"
SWAP_MODE_MODEL = "model"
SWAP_MODES = frozenset({SWAP_MODE_VARIANT, SWAP_MODE_MODEL})


def _normalize_swap_mode(mode: Optional[str]) -> str:
    value = (mode or SWAP_MODE_VARIANT).strip().lower()
    return value if value in SWAP_MODES else SWAP_MODE_VARIANT


def _variant_option_dict(product: Product, ps: ProductSize, current_ps_id: int) -> dict[str, Any]:
    return {
        "product_size_id": ps.id,
        "product_id": product.id,
        "color": product.color or "",
        "size": ps.size or "",
        "quantity": ps.quantity or 0,
        "barcode": ps.barcode or "",
        "label": _format_variant_name(product, ps.size or ""),
        "is_current": ps.id == current_ps_id,
    }


def list_variant_options(
    order_id: str,
    order_product_id: int,
    *,
    mode: str = SWAP_MODE_VARIANT,
) -> dict[str, Any]:
    """Dostepne opcje zamiany: wariant (rodzina) albo model (caly magazyn)."""
    swap_mode = _normalize_swap_mode(mode)
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            return {"ok": False, "error": "Nie znaleziono zamowienia"}

        op = (
            db.query(OrderProduct)
            .filter(
                OrderProduct.id == order_product_id,
                OrderProduct.order_id == order_id,
            )
            .first()
        )
        if not op:
            return {"ok": False, "error": "Nie znaleziono pozycji zamowienia"}
        if not op.product_size_id:
            return {"ok": False, "error": "Pozycja nie jest powiazana z magazynem"}

        current_ps = db.query(ProductSize).filter(
            ProductSize.id == op.product_size_id
        ).first()
        if not current_ps or not current_ps.product:
            return {"ok": False, "error": "Brak produktu magazynowego"}

        current_product = current_ps.product
        variants: list[dict[str, Any]] = []

        if swap_mode == SWAP_MODE_MODEL:
            rows = (
                db.query(ProductSize, Product)
                .join(Product, Product.id == ProductSize.product_id)
                .all()
            )
            for ps, product in rows:
                variants.append(_variant_option_dict(product, ps, current_ps.id))
            variants.sort(
                key=lambda v: (
                    v["label"].lower(),
                    v["color"].lower(),
                    v["size"],
                )
            )
        else:
            family = _product_family_key(current_product)
            if any(family):
                siblings = (
                    db.query(Product)
                    .filter(
                        Product.category == current_product.category,
                        Product.brand == current_product.brand,
                        Product.series == current_product.series,
                    )
                    .all()
                )
            else:
                siblings = [current_product]

            for product in siblings:
                for ps in product.sizes or []:
                    variants.append(_variant_option_dict(product, ps, current_ps.id))
            variants.sort(key=lambda v: (v["color"].lower(), v["size"]))

        return {
            "ok": True,
            "mode": swap_mode,
            "order_product_id": op.id,
            "current": {
                "product_size_id": current_ps.id,
                "color": current_product.color or "",
                "size": current_ps.size or "",
                "label": _format_variant_name(current_product, current_ps.size or ""),
                "name": op.name,
                "quantity": op.quantity,
                "price_brutto": float(op.price_brutto) if op.price_brutto is not None else None,
            },
            "variants": variants,
            "can_edit": can_edit_order_items(_current_order_status(db, order_id)),
        }


def edit_order_item_variant(
    order_id: str,
    order_product_id: int,
    new_product_size_id: int,
    *,
    restore_previous_stock: bool = True,
    mode: str = SWAP_MODE_VARIANT,
) -> OrderItemEditResult:
    """Zamien pozycje: wariant (kolor/rozmiar) albo dowolny model z magazynu."""
    swap_mode = _normalize_swap_mode(mode)
    old_name = ""
    new_name = ""
    need_consume = False
    did_restore = False
    stock_was_consumed = False
    consume_payload: Optional[dict] = None

    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            return OrderItemEditResult("Nie znaleziono zamowienia", "error", not_found=True)

        current_status = _current_order_status(db, order_id)
        if not can_edit_order_items(current_status):
            return OrderItemEditResult(
                f"Edycja wariantu niedostepna w statusie „{current_status}”",
                "error",
            )

        op = (
            db.query(OrderProduct)
            .filter(
                OrderProduct.id == order_product_id,
                OrderProduct.order_id == order_id,
            )
            .first()
        )
        if not op:
            return OrderItemEditResult("Nie znaleziono pozycji zamowienia", "error", not_found=True)
        if not op.product_size_id:
            return OrderItemEditResult(
                "Pozycja nie jest powiazana z magazynem — nie mozna zmienic wariantu",
                "error",
            )

        old_ps = db.query(ProductSize).filter(ProductSize.id == op.product_size_id).first()
        new_ps = db.query(ProductSize).filter(ProductSize.id == new_product_size_id).first()
        if not old_ps or not old_ps.product:
            return OrderItemEditResult("Brak starego wariantu w magazynie", "error")
        if not new_ps or not new_ps.product:
            return OrderItemEditResult("Wybrany wariant nie istnieje", "error")
        if new_ps.id == old_ps.id:
            return OrderItemEditResult("Wybrano ten sam wariant", "warning")
        if swap_mode == SWAP_MODE_VARIANT and not _same_family(old_ps.product, new_ps.product):
            return OrderItemEditResult(
                "W trybie wariant mozna zmienic tylko kolor/rozmiar w tej samej rodzinie "
                "(category/brand/series). Wybierz tryb model, aby zamienic na inny produkt.",
                "error",
            )

        qty = int(op.quantity or 1)
        old_name = op.name or _format_variant_name(old_ps.product, old_ps.size or "")
        new_name = _format_variant_name(new_ps.product, new_ps.size or "")
        stock_was_consumed = _order_has_consumed_stock(db, order_id)

        if restore_previous_stock and stock_was_consumed:
            from .return_stock import _restore_stock_for_return_item

            _restore_stock_for_return_item(db, order_id, old_ps, qty)
            did_restore = True

        op.product_size_id = new_ps.id
        op.ean = new_ps.barcode or op.ean
        op.name = new_name
        order.items_locally_edited = True

        change_label = "Zmiana modelu" if swap_mode == SWAP_MODE_MODEL else "Zmiana wariantu"
        add_order_status(
            db,
            order_id,
            current_status,
            skip_if_same=False,
            allow_backwards=True,
            send_email=False,
            notes=f"{change_label}: {old_name} → {new_name}",
        )

        if stock_was_consumed:
            need_consume = True
            price = Decimal(str(op.price_brutto or 0))
            from ..sales import calculate_shipping

            shipping = calculate_shipping(price)
            commission = (
                price * Decimal(str(settings.COMMISSION_ALLEGRO)) / Decimal("100")
            ).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
            consume_payload = {
                "product_id": new_ps.product_id,
                "size": new_ps.size,
                "quantity": qty,
                "sale_price": price,
                "shipping_cost": shipping,
                "commission_fee": commission,
            }

    if need_consume and consume_payload:
        consume_stock(
            consume_payload["product_id"],
            consume_payload["size"],
            consume_payload["quantity"],
            sale_price=consume_payload["sale_price"],
            shipping_cost=consume_payload["shipping_cost"],
            commission_fee=consume_payload["commission_fee"],
            order_id=order_id,
        )

    correction_number = None
    correction_errors: list[str] = []
    try:
        from .invoice_service import generate_variant_correction_invoice

        correction = generate_variant_correction_invoice(
            order_id=order_id,
            old_name=old_name,
            new_name=new_name,
        )
        if correction.get("skipped"):
            pass
        elif correction.get("success"):
            correction_number = correction.get("invoice_number")
        else:
            correction_errors = list(correction.get("errors") or [])
    except Exception as exc:
        logger.error("Blad korekty wariantu dla %s: %s", order_id, exc)
        correction_errors = [str(exc)]

    change_word = "model" if swap_mode == SWAP_MODE_MODEL else "wariant"
    parts = [f"Zmieniono {change_word}: {old_name} → {new_name}"]
    if did_restore:
        parts.append("przywrócono poprzedni produkt do magazynu")
    elif not restore_previous_stock:
        parts.append("poprzedni produkt NIE wrócił do magazynu")
    if need_consume:
        parts.append("odjęto nowy produkt od stanu")
    if correction_number:
        parts.append(f"korekta: {correction_number}")
    elif correction_errors:
        parts.append("uwaga: nie udało się wystawić korekty")

    return OrderItemEditResult(
        ". ".join(parts) + ".",
        "success" if not correction_errors else "warning",
        details={
            "old_name": old_name,
            "new_name": new_name,
            "mode": swap_mode,
            "restored_previous": did_restore,
            "consumed_new": need_consume,
            "stock_was_consumed": stock_was_consumed,
            "correction_number": correction_number,
            "correction_errors": correction_errors,
        },
    )


__all__ = [
    "EDIT_BLOCKED_STATUSES",
    "SWAP_MODE_MODEL",
    "SWAP_MODE_VARIANT",
    "SWAP_MODES",
    "OrderItemEditResult",
    "can_edit_order_items",
    "edit_order_item_variant",
    "list_variant_options",
]
