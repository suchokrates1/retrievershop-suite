import json
import secrets
from decimal import Decimal
from typing import Optional
from urllib.parse import urlencode

from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
)

from sqlalchemy import case, or_

from requests.exceptions import HTTPError, RequestException

from . import allegro_api
from .auth import login_required
from .config import settings
from .db import get_session
from .models import AllegroOffer, Product, ProductSize
from .allegro_sync import sync_offers
from .settings_store import SettingsPersistenceError, settings_store
from .env_tokens import update_allegro_tokens
from .allegro_scraper import fetch_competitors_for_offer, parse_price_amount

ALLEGRO_AUTHORIZATION_URL = "https://allegro.pl/auth/oauth/authorize"

bp = Blueprint("allegro", __name__)


def _format_debug_value(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except TypeError:
            return str(value)
    return str(value)


def _record_debug_step(steps: list[dict[str, str]], label: str, value: object) -> None:
    steps.append({"label": label, "value": _format_debug_value(value)})


def _append_debug_log(logs: Optional[list[str]], label: str, value: object) -> None:
    if logs is None:
        return
    formatted = _format_debug_value(value)
    if formatted:
        logs.append(f"{label}: {formatted}")
    else:
        logs.append(label)


def _process_oauth_response() -> dict[str, object]:
    debug_steps: list[dict[str, str]] = []

    expected_state = session.pop("allegro_oauth_state", None)
    _record_debug_step(debug_steps, "Oczekiwany state z sesji", expected_state)

    state = request.args.get("state")
    _record_debug_step(debug_steps, "State otrzymany z odpowiedzi", state)
    if not state or not expected_state or state != expected_state:
        current_app.logger.warning(
            "Allegro OAuth callback with invalid state",
            extra={"expected": expected_state, "received": state},
        )
        message = "Nieprawidłowy parametr state w odpowiedzi Allegro."
        return {"ok": False, "message": message, "debug_steps": debug_steps}

    code = request.args.get("code")
    _record_debug_step(debug_steps, "Kod autoryzacyjny Allegro", code)
    if not code:
        current_app.logger.warning("Allegro OAuth callback without authorization code")
        message = "Brak kodu autoryzacyjnego w odpowiedzi Allegro."
        return {"ok": False, "message": message, "debug_steps": debug_steps}

    client_id = settings_store.get("ALLEGRO_CLIENT_ID")
    client_secret = settings_store.get("ALLEGRO_CLIENT_SECRET")
    redirect_uri = settings_store.get("ALLEGRO_REDIRECT_URI")
    _record_debug_step(debug_steps, "ALLEGRO_CLIENT_ID", client_id)
    _record_debug_step(debug_steps, "ALLEGRO_CLIENT_SECRET", client_secret)
    _record_debug_step(debug_steps, "ALLEGRO_REDIRECT_URI", redirect_uri)
    if not client_id or not client_secret or not redirect_uri:
        current_app.logger.error(
            "Allegro OAuth callback missing configuration",
            extra={
                "has_client_id": bool(client_id),
                "has_client_secret": bool(client_secret),
                "has_redirect_uri": bool(redirect_uri),
            },
        )
        message = "Niekompletna konfiguracja Allegro."
        return {"ok": False, "message": message, "debug_steps": debug_steps}

    try:
        token_payload = allegro_api.get_access_token(
            client_id,
            client_secret,
            code,
            redirect_uri=redirect_uri,
        )
        _record_debug_step(debug_steps, "Odpowiedź Allegro z tokenami", token_payload)
    except HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        error_payload = {
            "status_code": status_code,
            "details": str(exc),
        }
        _record_debug_step(debug_steps, "Błąd HTTP podczas pobierania tokenu", error_payload)
        if status_code:
            current_app.logger.exception(
                "Allegro access token request failed",
                extra={"status_code": status_code},
            )
            message = f"Nie udało się uzyskać tokenów Allegro: HTTP status {status_code}."
        else:
            current_app.logger.exception(
                "Allegro access token request failed with HTTP error"
            )
            message = "Nie udało się uzyskać tokenów Allegro: błąd HTTP."
        return {"ok": False, "message": message, "debug_steps": debug_steps}
    except RequestException as exc:
        _record_debug_step(
            debug_steps,
            "Wyjątek podczas wywołania Allegro",
            {"exception": str(exc)},
        )
        current_app.logger.exception("Allegro access token request raised exception")
        message = f"Nie udało się uzyskać tokenów Allegro: {exc}"
        return {"ok": False, "message": message, "debug_steps": debug_steps}

    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    expires_in_raw = token_payload.get("expires_in")
    _record_debug_step(debug_steps, "Access token", access_token)
    _record_debug_step(debug_steps, "Refresh token", refresh_token)
    _record_debug_step(debug_steps, "Wartość expires_in z odpowiedzi", expires_in_raw)
    if not access_token or not refresh_token:
        message = "Nieprawidłowa odpowiedź Allegro: brak tokenów."
        return {"ok": False, "message": message, "debug_steps": debug_steps}

    expires_in: Optional[int]
    try:
        expires_in = int(expires_in_raw) if expires_in_raw is not None else None
    except (TypeError, ValueError):
        expires_in = None
    _record_debug_step(debug_steps, "Przetworzony expires_in", expires_in)

    metadata: dict[str, object] = {}
    if token_payload.get("scope"):
        metadata["scope"] = token_payload["scope"]
    if token_payload.get("token_type"):
        metadata["token_type"] = token_payload["token_type"]
    if expires_in is not None:
        metadata["expires_in"] = expires_in
    _record_debug_step(debug_steps, "Metadane tokenu", metadata)

    try:
        update_allegro_tokens(access_token, refresh_token, expires_in, metadata)
        _record_debug_step(debug_steps, "Wynik zapisu tokenów", "Sukces")
    except SettingsPersistenceError:
        _record_debug_step(debug_steps, "Błąd zapisu tokenów", "SettingsPersistenceError")
        current_app.logger.exception(
            "Failed to persist Allegro OAuth tokens", exc_info=True
        )
        message = "Nie udało się zapisać tokenów Allegro. Spróbuj ponownie."
        return {"ok": False, "message": message, "debug_steps": debug_steps}

    current_app.logger.info("Successfully obtained Allegro OAuth tokens")
    message = "Autoryzacja Allegro zakończona sukcesem."
    return {"ok": True, "message": message, "debug_steps": debug_steps}


@bp.post("/allegro/authorize")
@login_required
def authorize():
    client_id = settings_store.get("ALLEGRO_CLIENT_ID")
    redirect_uri = settings_store.get("ALLEGRO_REDIRECT_URI")
    if not client_id or not redirect_uri:
        current_app.logger.warning(
            "Cannot start Allegro authorization: missing client_id or redirect_uri",
        )
        flash("Uzupełnij konfigurację Allegro, aby rozpocząć autoryzację.")
        return redirect(url_for("settings_page"))

    state = secrets.token_urlsafe(16)
    session["allegro_oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    authorization_url = f"{ALLEGRO_AUTHORIZATION_URL}?{urlencode(params)}"
    current_app.logger.info("Redirecting user to Allegro authorization page")
    return redirect(authorization_url)


@bp.get("/allegro/oauth/callback")
@login_required
def allegro_oauth_callback():
    result = _process_oauth_response()
    if message := result.get("message"):
        flash(message)
    return redirect(url_for("settings_page"))


@bp.get("/allegro")
@login_required
def allegro_oauth_debug():
    result = _process_oauth_response()
    if message := result.get("message"):
        flash(message)
    return redirect(url_for("settings_page"))


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


def build_price_checks(
    debug_steps: Optional[list[dict[str, str]]] = None,
    debug_logs: Optional[list[str]] = None,
) -> list[dict]:
    def record_debug(label: str, value: object) -> None:
        if debug_steps is not None:
            _record_debug_step(debug_steps, label, value)
        _append_debug_log(debug_logs, label, value)

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
                    "product_size_id": offer.product_size_id,
                }
            )

    record_debug("Liczba powiązanych ofert", len(offers))

    offers_by_barcode: dict[str, list[dict]] = {}
    offers_without_barcode: list[dict] = []
    for offer in offers:
        barcode_list = [code for code in offer["barcodes"] if code]
        if barcode_list and offer["product_size_id"] is not None:
            for barcode in barcode_list:
                offers_by_barcode.setdefault(barcode, []).append(offer)
        else:
            offers_without_barcode.append(offer)

    record_debug(
        "Liczba grup kodów kreskowych",
        {"grupy": len(offers_by_barcode), "bez_kodu": len(offers_without_barcode)},
    )
    if offers_without_barcode:
        record_debug(
            "Oferty bez kodu kreskowego",
            [
                {
                    "offer_id": offer["offer_id"],
                    "title": offer["title"],
                    "barcodes": offer["barcodes"],
                }
                for offer in offers_without_barcode
            ],
        )

    results_by_offer: dict[str, dict[str, object]] = {}

    def process_competitor_lookup(
        *,
        reference_offer: dict,
        barcode: Optional[str],
        target_offers: list[dict],
    ) -> None:
        offer_id = reference_offer["offer_id"]
        offer_url = f"https://allegro.pl/oferta/{offer_id}"

        context = {"offer_id": offer_id, "url": offer_url}
        if barcode:
            context["barcode"] = barcode
            record_debug(
                "Sprawdzanie ofert Allegro dla kodu kreskowego",
                context,
            )
        else:
            record_debug("Sprawdzanie oferty Allegro", context)

        competitor_min_price: Optional[Decimal] = None
        competitor_min_url: Optional[str] = None
        error: Optional[str] = None

        try:
            competitor_offers, scrape_logs = fetch_competitors_for_offer(
                offer_id,
                stop_seller=settings.ALLEGRO_SELLER_NAME,
            )
        except Exception as exc:  # pragma: no cover - selenium/network errors
            error = str(exc)
            error_context = {"offer_id": offer_id, "url": offer_url, "error": str(exc)}
            if barcode:
                error_context["barcode"] = barcode
            record_debug("Błąd pobierania ofert Allegro", error_context)
            competitor_offers = []
            scrape_logs = []
        else:
            for entry in scrape_logs:
                log_context = {"offer_id": offer_id, "message": entry}
                if barcode:
                    log_context["barcode"] = barcode
                record_debug("Log Selenium", log_context)

        count_context = {"offer_id": offer_id, "offers": len(competitor_offers)}
        if barcode:
            count_context["barcode"] = barcode
        record_debug("Oferty konkurencji – liczba ofert", count_context)

        for competitor in competitor_offers:
            seller_name = (competitor.seller or "").strip().lower()
            if (
                settings.ALLEGRO_SELLER_NAME
                and seller_name
                and seller_name == settings.ALLEGRO_SELLER_NAME.lower()
            ):
                continue
            price_value = parse_price_amount(competitor.price)
            if price_value is None:
                continue
            if (
                competitor_min_price is None
                or price_value < competitor_min_price
                or (
                    price_value == competitor_min_price and competitor_min_url is None
                )
            ):
                competitor_min_price = price_value
                competitor_min_url = competitor.url

        if barcode:
            record_debug(
                "Najniższa cena konkurencji dla kodu",
                {
                    "barcode": barcode,
                    "price": _format_decimal(competitor_min_price),
                    "url": competitor_min_url,
                },
            )

        if competitor_min_price is not None:
            error = None

        for offer in target_offers:
            results_by_offer[offer["offer_id"]] = {
                "competitor_price": competitor_min_price,
                "competitor_url": competitor_min_url,
                "error": error,
            }

    for barcode, grouped_offers in offers_by_barcode.items():
        record_debug(
            "Grupa ofert dla kodu kreskowego",
            {
                "barcode": barcode,
                "offers": [
                    {
                        "offer_id": offer["offer_id"],
                        "price": _format_decimal(offer["price"]),
                    }
                    for offer in grouped_offers
                ],
            },
        )
        process_competitor_lookup(
            reference_offer=grouped_offers[0],
            barcode=barcode,
            target_offers=grouped_offers,
        )

    for offer in offers_without_barcode:
        process_competitor_lookup(
            reference_offer=offer,
            barcode=None,
            target_offers=[offer],
        )

    price_checks: list[dict] = []
    for offer in offers:
        result = results_by_offer.get(
            offer["offer_id"],
            {"competitor_price": None, "competitor_url": None, "error": None},
        )
        competitor_min = result["competitor_price"]
        is_lowest = None
        if offer["price"] is not None:
            if competitor_min is None:
                is_lowest = True
            else:
                is_lowest = offer["price"] <= competitor_min

        price_checks.append(
            {
                "offer_id": offer["offer_id"],
                "title": offer["title"],
                "label": offer["label"],
                "own_price": _format_decimal(offer["price"]),
                "competitor_price": _format_decimal(competitor_min),
                "is_lowest": is_lowest,
                "error": result["error"],
                "competitor_offer_url": result["competitor_url"],
            }
        )

    return price_checks


@bp.route("/allegro/price-check")
@login_required
def price_check():
    debug_steps: list[dict[str, str]] = []
    debug_log_lines: list[str] = []

    def record_debug(label: str, value: object) -> None:
        _record_debug_step(debug_steps, label, value)
        _append_debug_log(debug_log_lines, label, value)

    access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    refresh_token = settings_store.get("ALLEGRO_REFRESH_TOKEN")

    record_debug("Czy dostępny access token Allegro", bool(access_token))
    record_debug("Czy dostępny refresh token Allegro", bool(refresh_token))

    auth_error = None
    if not access_token or not refresh_token:
        auth_error = (
            "Brak połączenia z Allegro. Kliknij „Połącz z Allegro” w ustawieniach, "
            "aby ponownie autoryzować aplikację."
        )

    wants_json = (
        request.args.get("format") == "json"
        or request.accept_mimetypes.best == "application/json"
    )

    record_debug("Żądany format odpowiedzi", "json" if wants_json else "html")

    if wants_json:
        if auth_error:
            return jsonify(
                {
                    "price_checks": [],
                    "auth_error": auth_error,
                    "debug_steps": debug_steps,
                    "debug_log": "\n".join(debug_log_lines),
                }
            )
        price_checks = build_price_checks(debug_steps, debug_log_lines)
        return jsonify(
            {
                "price_checks": price_checks,
                "auth_error": None,
                "debug_steps": debug_steps,
                "debug_log": "\n".join(debug_log_lines),
            }
        )

    return render_template(
        "allegro/price_check.html",
        auth_error=auth_error,
        debug_steps=debug_steps,
        debug_log="\n".join(debug_log_lines),
    )


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
