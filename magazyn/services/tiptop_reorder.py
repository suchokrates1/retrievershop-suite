"""Lista braków magazynowych do zamówienia na TipTop24."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from magazyn.config import settings
from magazyn.models.orders import Order, OrderProduct
from magazyn.models.products import Product, ProductSize
from magazyn.models.tiptop import (
    TipTopProductLink,
    TipTopReorderExclusion,
    TipTopVariant,
)
from magazyn.services.tiptop_catalog import TIPTOP_BASE, cart_item_from_link


@dataclass
class ReorderLine:
    product_size_id: int
    product_id: int
    name: str
    series: str | None
    color: str | None
    size: str
    stock: int
    sold_30d: int
    suggested_qty: int
    tiptop_url: str | None
    stock_id: int | None
    options: dict[str, int]
    match_type: str | None
    match_confidence: float | None
    selected: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tiptop_reorder_threshold() -> int:
    """Próg braków dla zamówień TipTop (osobny od alertów LOW_STOCK_THRESHOLD)."""
    raw = getattr(settings, "TIPTOP_REORDER_THRESHOLD", None)
    if raw is None or str(raw).strip() == "":
        # Fallback: dawniej używano LOW_STOCK_THRESHOLD
        raw = getattr(settings, "LOW_STOCK_THRESHOLD", 5)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 5
    return max(0, value)


def _sold_30d_by_product_size(db: Session) -> dict[int, int]:
    since = int((datetime.now() - timedelta(days=30)).timestamp())
    rows = (
        db.query(
            OrderProduct.product_size_id,
            func.coalesce(func.sum(OrderProduct.quantity), 0),
        )
        .join(Order, Order.order_id == OrderProduct.order_id)
        .filter(
            OrderProduct.product_size_id.isnot(None),
            Order.date_add >= since,
        )
        .group_by(OrderProduct.product_size_id)
        .all()
    )
    return {int(ps_id): int(qty or 0) for ps_id, qty in rows}


def _excluded_ids(db: Session) -> tuple[set[int], set[int]]:
    """Return (excluded_product_ids, excluded_product_size_ids)."""
    product_ids: set[int] = set()
    size_ids: set[int] = set()
    for row in db.query(TipTopReorderExclusion).all():
        if row.product_id is not None:
            product_ids.add(int(row.product_id))
        if row.product_size_id is not None:
            size_ids.add(int(row.product_size_id))
    return product_ids, size_ids


def build_reorder_candidates(
    db: Session,
    *,
    threshold: int | None = None,
    target: int | None = None,
    require_tiptop_link: bool = True,
) -> list[ReorderLine]:
    """Build sorted low-stock reorder lines (bestsellers first)."""
    thr = _tiptop_reorder_threshold() if threshold is None else int(threshold)
    tgt = thr if target is None else int(target)
    excl_products, excl_sizes = _excluded_ids(db)
    sold_map = _sold_30d_by_product_size(db)

    links = {
        link.product_size_id: link
        for link in db.query(TipTopProductLink)
        .options(
            joinedload(TipTopProductLink.variant).joinedload(TipTopVariant.product)
        )
        .all()
    }

    q = (
        db.query(ProductSize, Product)
        .join(Product, ProductSize.product_id == Product.id)
        .filter(ProductSize.quantity <= thr)
    )
    lines: list[ReorderLine] = []
    for ps, product in q.all():
        if ps.id in excl_sizes or product.id in excl_products:
            continue
        link = links.get(ps.id)
        if require_tiptop_link and link is None:
            continue

        stock = int(ps.quantity or 0)
        # Na liście braków zawsze proponuj co najmniej 1 szt. do uzupełnienia.
        suggested = max(1, tgt - stock)

        options: dict[str, int] = {}
        stock_id = None
        tip_url = None
        match_type = None
        match_conf = None
        if link is not None:
            item = cart_item_from_link(link, suggested)
            options = item["options"]
            stock_id = item["stock_id"]
            tip_url = item["tiptop_url"]
            match_type = link.match_type
            match_conf = link.match_confidence

        lines.append(
            ReorderLine(
                product_size_id=ps.id,
                product_id=product.id,
                name=product.name,
                series=product.series,
                color=product.color,
                size=ps.size,
                stock=stock,
                sold_30d=sold_map.get(ps.id, 0),
                suggested_qty=suggested,
                tiptop_url=tip_url,
                stock_id=stock_id,
                options=options,
                match_type=match_type,
                match_confidence=match_conf,
            )
        )

    lines.sort(key=lambda x: (-x.sold_30d, x.stock, x.name or "", x.size or ""))
    return lines


def add_exclusion(
    db: Session,
    *,
    product_id: int | None = None,
    product_size_id: int | None = None,
    reason: str | None = None,
) -> TipTopReorderExclusion:
    if product_id is None and product_size_id is None:
        raise ValueError("Wymagane product_id lub product_size_id")
    row = TipTopReorderExclusion(
        product_id=product_id,
        product_size_id=product_size_id,
        reason=reason,
    )
    db.add(row)
    db.flush()
    return row


def remove_exclusion(db: Session, exclusion_id: int) -> bool:
    row = db.get(TipTopReorderExclusion, exclusion_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def list_exclusions(db: Session) -> list[TipTopReorderExclusion]:
    return (
        db.query(TipTopReorderExclusion)
        .order_by(TipTopReorderExclusion.created_at.desc())
        .all()
    )


@dataclass
class ExclusionView:
    id: int
    product_id: int | None
    product_size_id: int | None
    reason: str | None
    label: str
    scope: str  # "product" | "size"


def list_exclusions_enriched(db: Session) -> list[ExclusionView]:
    """Exclusions with human-readable product labels for settings UI."""
    rows = list_exclusions(db)
    views: list[ExclusionView] = []
    for row in rows:
        label = ""
        scope = "product"
        if row.product_size_id is not None:
            scope = "size"
            ps = db.get(ProductSize, row.product_size_id)
            if ps is not None:
                prod = db.get(Product, ps.product_id)
                if prod is not None:
                    label = f"{prod.series or prod.name} / {prod.color or '—'} / {ps.size}"
                else:
                    label = f"Wariant #{row.product_size_id} ({ps.size})"
            else:
                label = f"Wariant #{row.product_size_id} (usunięty)"
        elif row.product_id is not None:
            prod = db.get(Product, row.product_id)
            if prod is not None:
                label = f"{prod.series or prod.name} / {prod.color or '—'} (cały produkt)"
            else:
                label = f"Produkt #{row.product_id} (usunięty)"
        else:
            label = f"Wykluczenie #{row.id}"
        views.append(
            ExclusionView(
                id=row.id,
                product_id=row.product_id,
                product_size_id=row.product_size_id,
                reason=row.reason,
                label=label,
                scope=scope,
            )
        )
    return views


def search_products_for_exclusion(db: Session, q: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Search warehouse products to permanently exclude from TipTop reorder."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    rows = (
        db.query(Product)
        .filter(
            (Product._name.ilike(like))
            | (Product.color.ilike(like))
            | (Product.series.ilike(like))
            | (Product.category.ilike(like))
        )
        .order_by(Product.series, Product.color)
        .limit(limit)
        .all()
    )
    return [
        {
            "product_id": p.id,
            "label": f"{p.series or p.name} / {p.color or '—'} ({p.category or ''})",
        }
        for p in rows
    ]


def build_cart_payload(
    db: Session,
    selections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build TipTop Front API items from UI selections.

    Each selection: {product_size_id, quantity}.
    """
    items: list[dict[str, Any]] = []
    for sel in selections:
        ps_id = int(sel["product_size_id"])
        qty = int(sel.get("quantity") or 0)
        if qty <= 0:
            continue
        link = (
            db.query(TipTopProductLink)
            .options(
                joinedload(TipTopProductLink.variant).joinedload(TipTopVariant.product)
            )
            .filter(TipTopProductLink.product_size_id == ps_id)
            .one_or_none()
        )
        if link is None:
            continue
        items.append(cart_item_from_link(link, qty))
    return items


TIPTOP_ADD_URL = f"{TIPTOP_BASE}/pl/basket/add/post"
TIPTOP_BASKET_URL = f"{TIPTOP_BASE}/pl/basket"


def cart_item_to_add_fields(item: dict[str, Any]) -> dict[str, str]:
    """Pola formularza HTML TipTop ``/pl/basket/add/post`` (top-level, z cookie)."""
    fields: dict[str, str] = {
        "stock_id": str(int(item["stock_id"])),
        "quantity": str(int(item["quantity"])),
        "nojs": "1",
    }
    for key, value in (item.get("options") or {}).items():
        fields[f"option_{key}"] = str(int(value))
    return fields


def build_browser_fill_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Payload dla one-click napełniania koszyka w przeglądarce użytkownika."""
    out: list[dict[str, Any]] = []
    for it in items:
        if not it.get("stock_id"):
            continue
        out.append(
            {
                "label": it.get("label") or "",
                "fields": cart_item_to_add_fields(it),
            }
        )
    return out


# Zachowane pod stare testy / debug — Front API na originie TipTop.
def build_filler_script(items: list[dict[str, Any]]) -> str:
    payload = [
        {
            "stock_id": int(it["stock_id"]),
            "quantity": int(it["quantity"]),
            "options": {str(k): int(v) for k, v in (it.get("options") or {}).items()},
        }
        for it in items
        if it.get("stock_id")
    ]
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""(async () => {{
  const items = {data_json};
  const endpoint = '/webapi/front/pl_PL/basket/PLN/';
  for (const item of items) {{
    await fetch(endpoint, {{
      method: 'POST',
      credentials: 'same-origin',
      headers: {{
        'Content-Type': 'application/json;charset=UTF-8',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      }},
      body: JSON.stringify({{
        stock_id: item.stock_id,
        quantity: item.quantity,
        options: item.options || {{}}
      }})
    }});
  }}
  location.href = '/pl/basket';
}})();"""


__all__ = [
    "ExclusionView",
    "ReorderLine",
    "TIPTOP_ADD_URL",
    "TIPTOP_BASKET_URL",
    "add_exclusion",
    "build_browser_fill_items",
    "build_cart_payload",
    "build_filler_script",
    "build_reorder_candidates",
    "cart_item_to_add_fields",
    "list_exclusions",
    "list_exclusions_enriched",
    "remove_exclusion",
    "search_products_for_exclusion",
    "_tiptop_reorder_threshold",
]
