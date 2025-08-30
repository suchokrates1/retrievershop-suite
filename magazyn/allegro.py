from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)

from .db import get_session
from .models import AllegroOffer, Product
from .auth import login_required

bp = Blueprint("allegro", __name__)


def sync_offers():
    """Synchronize offers from Allegro API (placeholder)."""
    return []


@bp.route("/allegro/offers")
@login_required
def offers():
    with get_session() as db:
        rows = (
            db.query(AllegroOffer, Product)
            .outerjoin(Product, AllegroOffer.product_id == Product.id)
            .all()
        )
        offers = [
            {
                "offer_id": offer.offer_id,
                "title": offer.title,
                "price": offer.price,
                "product_name": product.name if product else None,
            }
            for offer, product in rows
        ]
    return render_template("allegro/offers.html", offers=offers)


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
