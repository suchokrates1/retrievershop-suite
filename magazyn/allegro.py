from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)

from sqlalchemy import case

from .db import get_session
from .models import AllegroOffer, Product, ProductSize
from .auth import login_required
from .allegro_sync import sync_offers

bp = Blueprint("allegro", __name__)


@bp.route("/allegro/offers")
@login_required
def offers():
    with get_session() as db:
        rows = (
            db.query(AllegroOffer, ProductSize, Product)
            .outerjoin(ProductSize, AllegroOffer.product_size_id == ProductSize.id)
            .outerjoin(Product, ProductSize.product_id == Product.id)
            .order_by(
                case((AllegroOffer.product_size_id.is_(None), 0), else_=1),
                AllegroOffer.title,
            )
            .all()
        )
        offers = []
        for offer, size, product in rows:
            label = None
            if product and size:
                parts = [product.name]
                if product.color:
                    parts.append(product.color)
                label = " – ".join([" ".join(parts), size.size])
            offers.append(
                {
                    "offer_id": offer.offer_id,
                    "title": offer.title,
                    "price": offer.price,
                    "product_size_id": offer.product_size_id,
                    "selected_label": label,
                    "barcode": size.barcode if size else None,
                }
            )

        inventory_rows = (
            db.query(ProductSize, Product)
            .join(Product, ProductSize.product_id == Product.id)
            .order_by(Product.name, ProductSize.size)
            .all()
        )
        inventory = []
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
                ]
            ).strip().lower()
            inventory.append(
                {
                    "id": size.id,
                    "label": label,
                    "extra": ", ".join(extra_parts),
                    "filter": filter_text,
                }
            )
    return render_template("allegro/offers.html", offers=offers, inventory=inventory)


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
