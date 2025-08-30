from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)

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
            .all()
        )
        grouped = {}
        for offer, size, product in rows:
            key = size.id if size else None
            group = grouped.setdefault(
                key,
                {
                    "product_name": product.name if product else None,
                    "size": size.size if size else None,
                    "offers": [],
                },
            )
            group["offers"].append(
                {
                    "offer_id": offer.offer_id,
                    "title": offer.title,
                    "price": offer.price,
                }
            )
    return render_template("allegro/offers.html", groups=grouped.values())


@bp.route("/allegro/refresh", methods=["POST"])
@login_required
def refresh():
    try:
        sync_offers()
        flash("Oferty zaktualizowane")
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
            product_id = request.form.get("product_id", type=int)
            if product_id:
                product = db.query(Product).filter_by(id=product_id).first()
                if product:
                    offer.product_id = product.id
                    flash("Powiązano aukcję z produktem")
                    return redirect(url_for("allegro.offers"))
                flash("Nie znaleziono produktu o podanym ID")
            else:
                flash("Nie podano ID produktu")

        offer_data = {
            "offer_id": offer.offer_id,
            "title": offer.title,
            "price": offer.price,
            "product_id": offer.product_id or "",
        }
    return render_template("allegro/link.html", offer=offer_data)
