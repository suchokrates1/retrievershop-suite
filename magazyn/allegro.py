from decimal import Decimal, InvalidOperation
from typing import Optional

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)

from sqlalchemy import case, or_

from .allegro_price_monitor import fetch_product_listing
from .auth import login_required
from .config import settings
from .db import get_session
from .models import AllegroOffer, Product, ProductSize
from .allegro_sync import sync_offers

bp = Blueprint("allegro", __name__)


@bp.route("/allegro/offers")
@login_required
def offers():
    with get_session() as db:
        rows = (
            db.query(AllegroOffer, ProductSize, Product)
            .outerjoin(ProductSize, AllegroOffer.product_size_id == ProductSize.id)
            .outerjoin(Product, AllegroOffer.product_id == Product.id)
            .order_by(
                case((AllegroOffer.product_size_id.is_(None), 0), else_=1),
                AllegroOffer.title,
            )
            .all()
        )
        linked_offers: list[dict] = []
        unlinked_offers: list[dict] = []
        for offer, size, product in rows:
            label = None
            product_for_label = product or (size.product if size else None)
            if product_for_label and size:
                parts = [product_for_label.name]
                if product_for_label.color:
                    parts.append(product_for_label.color)
                label = " – ".join([" ".join(parts), size.size])
            elif product_for_label:
                parts = [product_for_label.name]
                if product_for_label.color:
                    parts.append(product_for_label.color)
                label = " ".join(parts)
            offer_data = {
                "offer_id": offer.offer_id,
                "title": offer.title,
                "price": offer.price,
                "product_size_id": offer.product_size_id,
                "product_id": offer.product_id,
                "selected_label": label,
                "barcode": size.barcode if size else None,
            }
            if offer.product_size_id or offer.product_id:
                linked_offers.append(offer_data)
            else:
                unlinked_offers.append(offer_data)

        inventory_rows = (
            db.query(ProductSize, Product)
            .join(Product, ProductSize.product_id == Product.id)
            .order_by(Product.name, ProductSize.size)
            .all()
        )
        product_rows = db.query(Product).order_by(Product.name).all()
        inventory: list[dict] = []
        product_inventory: list[dict] = []
        for product in product_rows:
            name_parts = [product.name]
            if product.color:
                name_parts.append(product.color)
            label = " ".join(name_parts)
            sizes = list(product.sizes or [])
            total_quantity = sum(
                size.quantity or 0 for size in sizes if size.quantity is not None
            )
            barcodes = sorted({size.barcode for size in sizes if size.barcode})
            extra_parts = ["Powiązanie na poziomie produktu"]
            if barcodes:
                extra_parts.append(f"EAN: {', '.join(barcodes)}")
            if sizes:
                extra_parts.append(f"Stan łączny: {total_quantity}")
            filter_values = [label, "produkt"]
            filter_values.extend(barcodes)
            if total_quantity:
                filter_values.append(str(total_quantity))
            product_inventory.append(
                {
                    "id": product.id,
                    "label": label,
                    "extra": ", ".join(extra_parts),
                    "filter": " ".join(filter_values).strip().lower(),
                    "type": "product",
                    "type_label": "Produkt",
                }
            )
        for size, product in inventory_rows:
            name_parts = [product.name]
            if product.color:
                name_parts.append(product.color)
            main_label = " ".join(name_parts)
            label = f"{main_label} – {size.size}"
            extra_parts = []
            if size.barcode:
                extra_parts.append(f"EAN: {size.barcode}")
            quantity = size.quantity if size.quantity is not None else 0
            extra_parts.append(f"Stan: {quantity}")
            filter_text = " ".join(
                [
                    label,
                    size.barcode or "",
                    str(quantity),
                    "rozmiar",
                ]
            ).strip().lower()
            inventory.append(
                {
                    "id": size.id,
                    "label": label,
                    "extra": ", ".join(extra_parts),
                    "filter": filter_text,
                    "type": "size",
                    "type_label": "Rozmiar",
                }
            )
        inventory = product_inventory + inventory
    return render_template(
        "allegro/offers.html",
        unlinked_offers=unlinked_offers,
        linked_offers=linked_offers,
        inventory=inventory,
    )


def _format_decimal(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return f"{value:.2f}"


@bp.route("/allegro/price-check")
@login_required
def price_check():
    with get_session() as db:
        rows = (
            db.query(AllegroOffer, ProductSize, Product)
            .outerjoin(
                ProductSize, AllegroOffer.product_size_id == ProductSize.id
            )
            .outerjoin(
                Product,
                or_(
                    Product.id == AllegroOffer.product_id,
                    Product.id == ProductSize.product_id,
                ),
            )
            .filter(
                or_(
                    AllegroOffer.product_size_id.isnot(None),
                    AllegroOffer.product_id.isnot(None),
                )
            )
            .all()
        )

        offers = []
        for offer, size, product in rows:
            product_for_label = product or (size.product if size else None)
            if not product_for_label:
                continue

            barcodes: list[str] = []
            if size:
                name_parts = [product_for_label.name]
                if product_for_label.color:
                    name_parts.append(product_for_label.color)
                label = " ".join(name_parts) + f" – {size.size}"
                if size.barcode:
                    barcodes.append(size.barcode)
            else:
                name_parts = [product_for_label.name]
                if product_for_label.color:
                    name_parts.append(product_for_label.color)
                label = " ".join(name_parts)
                related_sizes = list(product_for_label.sizes or [])
                for related_size in related_sizes:
                    if related_size.barcode:
                        barcodes.append(related_size.barcode)

            offers.append(
                {
                    "offer_id": offer.offer_id,
                    "title": offer.title,
                    "price": Decimal(offer.price).quantize(Decimal("0.01")),
                    "barcodes": barcodes,
                    "label": label,
                }
            )

    price_checks = []
    for offer in offers:
        competitor_min_price: Optional[Decimal] = None
        competitor_min_offer_id: Optional[str] = None
        error: Optional[str] = None
        barcodes = offer.get("barcodes", [])
        unique_barcodes: list[str] = []
        for barcode in barcodes:
            if barcode and barcode not in unique_barcodes:
                unique_barcodes.append(barcode)

        if unique_barcodes:
            for barcode in unique_barcodes:
                try:
                    listing = fetch_product_listing(barcode)
                except Exception as exc:  # pragma: no cover - network errors
                    error = str(exc)
                    continue
                for item in listing:
                    offer_id = item.get("id")
                    seller = item.get("seller") or {}
                    seller_id = seller.get("id")
                    if (
                        not seller_id
                        or seller_id == settings.ALLEGRO_SELLER_ID
                        or seller_id in settings.ALLEGRO_EXCLUDED_SELLERS
                    ):
                        continue
                    price_str = (
                        item.get("sellingMode", {})
                        .get("price", {})
                        .get("amount")
                    )
                    try:
                        price = Decimal(price_str).quantize(Decimal("0.01"))
                    except (TypeError, ValueError, InvalidOperation):
                        continue
                    if (
                        competitor_min_price is None
                        or price < competitor_min_price
                        or (
                            price == competitor_min_price
                            and competitor_min_offer_id is None
                        )
                    ):
                        competitor_min_price = price
                        competitor_min_offer_id = offer_id
            if competitor_min_price is not None:
                error = None
        else:
            error = "Brak kodu EAN"

        competitor_min = competitor_min_price
        is_lowest = None
        if offer["price"] is not None:
            if competitor_min is None:
                is_lowest = True
            else:
                is_lowest = offer["price"] <= competitor_min

        competitor_offer_url = (
            f"https://allegro.pl/oferta/{competitor_min_offer_id}"
            if competitor_min_offer_id
            else None
        )

        price_checks.append(
            {
                "offer_id": offer["offer_id"],
                "title": offer["title"],
                "label": offer["label"],
                "own_price": _format_decimal(offer["price"]),
                "competitor_price": _format_decimal(competitor_min),
                "is_lowest": is_lowest,
                "error": error,
                "competitor_offer_url": competitor_offer_url,
            }
        )

    return render_template("allegro/price_check.html", price_checks=price_checks)


@bp.route("/allegro/refresh", methods=["POST"])
@login_required
def refresh():
    try:
        result = sync_offers()
        fetched = result.get("fetched", 0)
        matched = result.get("matched", 0)
        flash(
            "Oferty zaktualizowane (pobrano {fetched}, zaktualizowano {matched})".format(
                fetched=fetched, matched=matched
            )
        )
    except Exception as e:
        flash(f"Błąd synchronizacji ofert: {e}")
    return redirect(url_for("allegro.offers"))


@bp.route("/allegro/link/<offer_id>", methods=["GET", "POST"])
@login_required
def link_offer(offer_id):
    with get_session() as db:
        offer = db.query(AllegroOffer).filter_by(offer_id=offer_id).first()
        if not offer:
            flash("Nie znaleziono aukcji")
            return redirect(url_for("allegro.offers"))

        if request.method == "POST":
            product_size_id = request.form.get("product_size_id", type=int)
            product_id = request.form.get("product_id", type=int)
            if product_size_id:
                product_size = (
                    db.query(ProductSize).filter_by(id=product_size_id).first()
                )
                if product_size:
                    offer.product_size_id = product_size.id
                    offer.product_id = product_size.product_id
                    flash("Powiązano ofertę z pozycją magazynową")
                else:
                    flash("Nie znaleziono rozmiaru produktu o podanym ID")
            elif product_id:
                product = db.query(Product).filter_by(id=product_id).first()
                if product:
                    offer.product_id = product.id
                    offer.product_size_id = None
                    flash("Powiązano aukcję z produktem")
                else:
                    flash("Nie znaleziono produktu o podanym ID")
            else:
                offer.product_size_id = None
                offer.product_id = None
                flash("Usunięto powiązanie z magazynem")
            return redirect(url_for("allegro.offers"))

        offer_data = {
            "offer_id": offer.offer_id,
            "title": offer.title,
            "price": offer.price,
            "product_id": offer.product_id or "",
            "product_size_id": offer.product_size_id or "",
        }
    return render_template("allegro/link.html", offer=offer_data)
