import base64
from decimal import Decimal
import json
import secrets
from typing import Callable, Optional
from queue import Queue
from threading import Thread
from urllib.parse import urlencode

from flask import (
    Blueprint,
    Response,
    current_app,
    make_response,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
    stream_with_context,
    has_app_context,
)

from sqlalchemy import case, or_, text
from .db import get_session, SessionLocal
from .models import AllegroOffer, Product, ProductSize, AllegroPriceHistory
from .allegro_sync import sync_offers
from .settings_store import SettingsPersistenceError, settings_store
from .env_tokens import update_allegro_tokens
from .print_agent import agent
from .auth import login_required
from .allegro_scraper import (
    AllegroScrapeError,
    fetch_competitors_for_offer,
    parse_price_amount,
)

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


def _append_debug_log(
    logs: Optional[list[str]], label: str, value: object
) -> tuple[str, str]:
    formatted = _format_debug_value(value)
    if formatted:
        line = f"{label}: {formatted}"
    else:
        line = label
    if logs is not None:
        logs.append(line)
    return formatted, line


def _sse_event(event: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def _format_decimal(value: Optional[Decimal]) -> Optional[str]:
    """Format decimal value for display."""
    if value is None:
        return None
    return f"{value:.2f}"


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
        agent.reload_config()
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


def _get_ean_for_offer(offer_id: str) -> str:
    """Get EAN for an offer from Allegro API."""
    print(f"DEBUG: Starting EAN lookup for offer {offer_id}, has_app_context: {has_app_context()}")
    current_app.logger.error(f"DEBUG: Starting EAN lookup for offer {offer_id}, has_app_context: {has_app_context()}")
    try:
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        if not access_token:
            current_app.logger.error(f"DEBUG: No Allegro access token for EAN lookup of offer {offer_id}")
            return ""
        
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.allegro.public.v1+json"}
        
        url1 = f"https://api.allegro.pl/sale/product-offers/{offer_id}"
        response1 = requests.get(url1, headers=headers, timeout=10)
        if response1.status_code != 200:
            current_app.logger.error(f"DEBUG: Allegro API error for offer {offer_id}: {response1.status_code}")
            return ""
        
        data1 = response1.json()
        product_set = data1.get("productSet", [])
        if not product_set:
            current_app.logger.error(f"DEBUG: No product set for offer {offer_id}")
            return ""
        
        product_id = product_set[0]["product"]["id"]
        
        url2 = f"https://api.allegro.pl/sale/products/{product_id}"
        response2 = requests.get(url2, headers=headers, timeout=10)
        if response2.status_code != 200:
            current_app.logger.error(f"DEBUG: Allegro product API error for {product_id}: {response2.status_code}")
            return ""
        
        data2 = response2.json()
        parameters = data2.get("parameters", [])
        current_app.logger.error(f"DEBUG: Found {len(parameters)} parameters for product {product_id}")
        for param in parameters:
            current_app.logger.error(f"DEBUG: Param name: '{param.get('name')}'")
            if param.get("name") == "EAN (GTIN)":
                values = param.get("values", [])
                current_app.logger.error(f"DEBUG: EAN values: {values}")
                if values:
                    current_app.logger.error(f"DEBUG: Returning EAN {values[0]} for offer {offer_id}")
                    return values[0]
                else:
                    current_app.logger.error(f"DEBUG: Empty EAN values for offer {offer_id}")
        current_app.logger.error(f"DEBUG: No EAN parameter found for offer {offer_id}")
        return ""
    except Exception as e:
        current_app.logger.error(f"DEBUG: Error getting EAN for offer {offer_id}: {e}")
        import traceback
        traceback.print_exc()
        return ""


@bp.route("/allegro/offers")
@login_required
def offers():
    with get_session() as db:
        rows = (
            db.query(AllegroOffer, ProductSize, Product)
            .filter(AllegroOffer.publication_status == 'ACTIVE')
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
            current_app.logger.error(f"DEBUG: Processing offer {offer.offer_id}")
            try:
                ean = _get_ean_for_offer(offer.offer_id)
                current_app.logger.error(f"DEBUG: EAN for offer {offer.offer_id}: '{ean}'")
            except Exception as e:
                current_app.logger.error(f"DEBUG: Error getting EAN for offer {offer.offer_id}: {e}")
                ean = ""
            offer_data = {
                "offer_id": offer.offer_id,
                "title": offer.title,
                "price": offer.price,
                "product_size_id": offer.product_size_id,
                "product_id": offer.product_id,
                "selected_label": label,
                "barcode": size.barcode if size else None,
                "ean": ean,
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
    response = make_response(render_template(
        "allegro/offers.html",
        unlinked_offers=unlinked_offers,
        linked_offers=linked_offers,
        inventory=inventory,
    ))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@bp.route("/offers-and-prices")
@login_required
def offers_and_prices():
    print("DEBUG PRINT: offers_and_prices called - START")
    current_app.logger.error("DEBUG: offers_and_prices called - START")
    with get_session() as db:
        # Get all active offers with their linked products
        rows = (
            db.query(AllegroOffer, ProductSize, Product)
            .filter(AllegroOffer.publication_status == 'ACTIVE')
            .outerjoin(ProductSize, AllegroOffer.product_size_id == ProductSize.id)
            .outerjoin(Product, AllegroOffer.product_id == Product.id)
            .order_by(
                case((AllegroOffer.product_size_id.is_(None), 0), else_=1),
                AllegroOffer.title,
            )
            .all()
        )

        offers_data = []
        for offer, size, product in rows:
            # Get latest competitor data from database (saved by scraper)
            latest_competitor = (
                db.query(AllegroPriceHistory)
                .filter(
                    AllegroPriceHistory.offer_id == offer.offer_id,
                    AllegroPriceHistory.competitor_price.isnot(None)
                )
                .order_by(AllegroPriceHistory.recorded_at.desc())
                .first()
            )
            
            current_app.logger.info(f"Offer {offer.offer_id}: latest_competitor = {latest_competitor}")
            
            current_app.logger.error(f"DEBUG: Offer {offer.offer_id}: latest_competitor = {latest_competitor}")
            
            competitors = []
            if latest_competitor:
                competitors = [{
                    'price': float(latest_competitor.competitor_price),
                    'seller': latest_competitor.competitor_seller,
                    'url': latest_competitor.competitor_url,
                    'delivery_days': latest_competitor.competitor_delivery_days
                }]
            
            current_app.logger.error(f"DEBUG: Offer {offer.offer_id}: competitors = {competitors}")

            # Calculate price statistics
            competitor_prices = [c['price'] for c in competitors if c.get('price')]
            avg_price = None
            min_price = None
            max_price = None
            if competitor_prices:
                avg_price = sum(competitor_prices) / len(competitor_prices)
                min_price = min(competitor_prices)
                max_price = max(competitor_prices)

            # Create label for linked product
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
                "ean": "",
                "competitors": competitors,
                "competitor_count": len(competitors),
                "avg_competitor_price": _format_decimal(avg_price),
                "min_competitor_price": _format_decimal(min_price),
                "max_competitor_price": _format_decimal(max_price),
                "is_linked": bool(offer.product_size_id or offer.product_id),
            }
            
            # Try to get EAN
            try:
                ean_value = _get_ean_for_offer(offer.offer_id)
                offer_data["ean"] = ean_value
                current_app.logger.error(f"DEBUG: Got EAN for offer {offer.offer_id}: '{ean_value}'")
            except Exception as e:
                current_app.logger.error(f"DEBUG: Error getting EAN for offer {offer.offer_id}: {e}")
                offer_data["ean"] = ""
            offers_data.append(offer_data)

        # Build inventory for dropdown
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

    response = make_response(render_template(
        "allegro/offers_and_prices.html",
        offers=offers_data,
        inventory=inventory,
    ))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _format_decimal(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return f"{value:.2f}"


def fetch_price_via_local_scraper(offer_url: str) -> Optional[Decimal]:
    """
    Fetch price from local scraper API running on PC.
    Returns price as Decimal or None if unavailable/error.
    """
    import requests
    
    scraper_url = settings.ALLEGRO_SCRAPER_API_URL
    if not scraper_url or not scraper_url.strip():
        return None
    
    scraper_url = scraper_url.rstrip('/')
    
    try:
        response = requests.get(
            f"{scraper_url}/check_price",
            params={"url": offer_url},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            price_str = data.get("price")
            if price_str:
                # Parse price: "159.89" or "159,89"
                price_str = price_str.replace(",", ".")
                return Decimal(price_str).quantize(Decimal("0.01"))
        elif response.status_code == 503:
            # CAPTCHA - log but don't fail
            current_app.logger.warning(
                "CAPTCHA detected by local scraper for %s", offer_url
            )
        else:
            current_app.logger.error(
                "Local scraper error %s: %s", response.status_code, response.text
            )
    except requests.RequestException as e:
        current_app.logger.error(
            "Failed to connect to local scraper at %s: %s", scraper_url, e
        )
    except (ValueError, TypeError) as e:
        current_app.logger.error("Failed to parse price from scraper: %s", e)
    
    return None


def fetch_prices_batch_via_scraper(eans: list[str]) -> dict[str, Optional[Decimal]]:
    """
    Fetch prices for multiple EANs via local scraper API.
    Returns dict: {ean: price_decimal or None}
    """
    import requests
    
    scraper_url = settings.ALLEGRO_SCRAPER_API_URL
    if not scraper_url or not scraper_url.strip():
        return {}
    
    scraper_url = scraper_url.rstrip('/')
    
    try:
        response = requests.post(
            f"{scraper_url}/check_prices_batch",
            json={"eans": eans},
            timeout=len(eans) * 5 + 30  # 5 seconds per EAN + 30s buffer
        )
        
        if response.status_code == 200:
            data = response.json()
            results = {}
            
            for item in data.get("results", []):
                ean = item.get("ean")
                price_str = item.get("price")
                
                if price_str:
                    try:
                        price_str = price_str.replace(",", ".")
                        results[ean] = Decimal(price_str).quantize(Decimal("0.01"))
                    except (ValueError, TypeError):
                        results[ean] = None
                else:
                    results[ean] = None
                    if item.get("error"):
                        current_app.logger.warning(
                            "Scraper error for EAN %s: %s", ean, item["error"]
                        )
            
            return results
        else:
            current_app.logger.error(
                "Batch scraper error %s: %s", response.status_code, response.text
            )
            return {}
            
    except requests.RequestException as e:
        current_app.logger.error(
            "Failed to connect to batch scraper at %s: %s", scraper_url, e
        )
        return {}


def build_price_checks(
    debug_steps: Optional[list[dict[str, str]]] = None,
    debug_logs: Optional[list[str]] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
    screenshot_callback: Optional[Callable[[dict], None]] = None,
) -> list[dict]:
    def record_debug(label: str, value: object) -> None:
        if debug_steps is not None:
            _record_debug_step(debug_steps, label, value)
        formatted, _ = _append_debug_log(debug_logs, label, value)
        if log_callback is not None:
            log_callback(label, formatted)

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
    
    # Create scraping tasks for all EANs
    all_eans = list(offers_by_barcode.keys())
    
    if all_eans:
        session = SessionLocal()
        try:
            record_debug("Tworzenie zadań scrapowania", {"count": len(all_eans), "eans": all_eans})
            
            for ean in all_eans:
                session.execute(
                    text("""
                    INSERT INTO scraper_tasks (ean, status, created_at)
                    VALUES (:ean, 'pending', CURRENT_TIMESTAMP)
                    """),
                    {"ean": ean}
                )
                session.commit()
                
                # Check for existing results from scraper
                placeholders = ",".join([f":ean{i}" for i in range(len(all_eans))])
                params = {f"ean{i}": ean for i, ean in enumerate(all_eans)}
                
                result_query = session.execute(
                    text(f"""
                    SELECT ean, price, url, error
                    FROM scraper_tasks
                    WHERE ean IN ({placeholders})
                      AND status = 'done'
                      AND completed_at > datetime('now', '-1 hour')
                    ORDER BY completed_at DESC
                    """),
                    params
                )
                rows = result_query.fetchall()
                
                # Use latest results
                ean_results = {}
                for row in rows:
                    ean = row[0]
                    if ean not in ean_results:  # Take first (latest) result
                        ean_results[ean] = {
                            "price": row[1],
                            "url": row[2],
                            "error": row[3]
                        }
                
                # Map results to offers
                for barcode, grouped_offers in offers_by_barcode.items():
                    result = ean_results.get(barcode)
                    
                    if result and result["price"]:
                        # Found price
                        for offer in grouped_offers:
                            results_by_offer[offer["offer_id"]] = {
                                "competitor_price": result["price"],
                                "competitor_url": result["url"],
                                "error": None,
                            }
                        record_debug(
                            "Najniższa cena dla EAN (z cache)",
                            {"ean": barcode, "price": _format_decimal(result["price"])}
                        )
        finally:
            session.close()

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
        
        # Try local scraper first if configured
        if settings.ALLEGRO_SCRAPER_API_URL:
            record_debug("Używanie lokalnego scrapera", {"url": settings.ALLEGRO_SCRAPER_API_URL})
            try:
                price = fetch_price_via_local_scraper(offer_url)
                if price is not None:
                    competitor_min_price = price
                    competitor_min_url = offer_url
                    record_debug(
                        "Cena z lokalnego scrapera",
                        {"price": _format_decimal(price), "url": offer_url}
                    )
                else:
                    record_debug("Lokalny scraper nie zwrócił ceny", {})
            except Exception as exc:
                record_debug("Błąd lokalnego scrapera", {"error": str(exc)})
                # Fall through to selenium scraper below
        
        # If local scraper didn't work, use selenium (old method)
        if competitor_min_price is None:
            def stream_scrape_log(message: str) -> None:
                log_context = {"offer_id": offer_id, "message": message}
                if barcode:
                    log_context["barcode"] = barcode
                record_debug("Log Selenium", log_context)

            scraper_callback = stream_scrape_log if log_callback is not None else None

            def stream_screenshot(image: bytes, stage: str) -> None:
                if screenshot_callback is None:
                    return
                payload = {
                    "offer_id": offer_id,
                    "stage": stage,
                    "image": base64.b64encode(image).decode("ascii"),
                }
                if barcode:
                    payload["barcode"] = barcode
                screenshot_callback(payload)

            screenshot_handler = stream_screenshot if screenshot_callback is not None else None

            try:
                competitor_offers, scrape_logs = fetch_competitors_for_offer(
                    offer_id,
                    stop_seller=settings.ALLEGRO_SELLER_NAME,
                    log_callback=scraper_callback,
                    screenshot_callback=screenshot_handler,
                )
            except AllegroScrapeError as exc:  # pragma: no cover - selenium/network errors
                error = str(exc)
                error_context = {"offer_id": offer_id, "url": offer_url, "error": str(exc)}
                if barcode:
                    error_context["barcode"] = barcode
                record_debug("Błąd pobierania ofert Allegro", error_context)
                competitor_offers = []
                scrape_logs = exc.logs
            except Exception as exc:  # pragma: no cover - selenium/network errors
                error = str(exc)
                error_context = {"offer_id": offer_id, "url": offer_url, "error": str(exc)}
                if barcode:
                    error_context["barcode"] = barcode
                record_debug("Błąd pobierania ofert Allegro", error_context)
                competitor_offers = []
                scrape_logs = []

            if log_callback is None:
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
        # Skip if already processed by batch scraper
        first_offer_id = grouped_offers[0]["offer_id"]
        if first_offer_id in results_by_offer:
            record_debug(
                "Grupa ofert już przetworzona przez batch scraper",
                {"barcode": barcode, "offers": len(grouped_offers)}
            )
            continue
            
        record_debug(
            "Grupa ofert dla kodu kreskowego - fallback Selenium",
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

    wants_json = (
        request.args.get("format") == "json"
        or request.accept_mimetypes.best == "application/json"
    )

    record_debug("Żądany format odpowiedzi", "json" if wants_json else "html")

    if wants_json:
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
        auth_error=None,
        debug_steps=debug_steps,
        debug_log="\n".join(debug_log_lines),
    )


@bp.route("/allegro/price-check/stream")
@login_required
def price_check_stream():
    def event_stream():
        queue: "Queue[Optional[str]]" = Queue()
        debug_steps: list[dict[str, str]] = []
        debug_log_lines: list[str] = []

        def push_log(label: str, value: str) -> None:
            line = f"{label}: {value}" if value else label
            queue.put(
                _sse_event(
                    "log",
                    {
                        "label": label,
                        "value": value,
                        "line": line,
                    },
                )
            )

        def push_screenshot(data: dict) -> None:
            queue.put(_sse_event("screenshot", data))

        def run_price_check() -> None:
            try:
                price_checks = build_price_checks(
                    debug_steps,
                    debug_log_lines,
                    log_callback=push_log,
                    screenshot_callback=push_screenshot,
                )
                queue.put(
                    _sse_event(
                        "result",
                        {
                            "price_checks": price_checks,
                            "auth_error": None,
                            "debug_steps": debug_steps,
                            "debug_log": "\n".join(debug_log_lines),
                        },
                    )
                )
            except Exception as exc:  # pragma: no cover - unexpected errors
                current_app.logger.exception("Price check stream failed")
                queue.put(
                    _sse_event("error", {"message": str(exc)})
                )
            finally:
                queue.put(None)

        worker = Thread(target=run_price_check, daemon=True)
        worker.start()

        while True:
            item = queue.get()
            if item is None:
                break
            yield item

    response = Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


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
