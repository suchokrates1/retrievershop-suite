import base64
from decimal import Decimal
import json
import requests
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
from .config import settings
from .env_tokens import update_allegro_tokens
from .print_agent import agent
from .auth import login_required
from .allegro_scraper import (
    AllegroScrapeError,
    fetch_competitors_for_offer,
    parse_price_amount,
)
from .allegro_helpers import build_inventory_list, format_decimal
from . import allegro_api
from requests.exceptions import HTTPError

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
    """Format decimal value for display. Delegacja do allegro_helpers."""
    return format_decimal(value)


def _process_oauth_response() -> dict[str, object]:
    debug_steps: list[dict[str, str]] = []

    # Loguj wszystkie parametry z callbacka (w tym bledy od Allegro)
    all_args = dict(request.args)
    _record_debug_step(debug_steps, "Wszystkie parametry callbacka", all_args)
    current_app.logger.info(f"Allegro OAuth callback args: {all_args}")
    
    # Sprawdz czy Allegro zwrocilo blad
    error = request.args.get("error")
    error_description = request.args.get("error_description")
    if error:
        current_app.logger.error(f"Allegro OAuth error: {error} - {error_description}")
        message = f"Allegro zwrocilo blad: {error}. {error_description or ''}"
        return {"ok": False, "message": message, "debug_steps": debug_steps}

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

    # Nie podajemy scope'ow - Allegro da wszystkie zadeklarowane dla aplikacji w Developer Apps
    # Jesli potrzebujesz allegro:api:billing:read, wlacz go w panelu https://apps.developer.allegro.pl/

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
    try:
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        if not access_token:
            return ""
        
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.allegro.public.v1+json"}
        
        url1 = f"https://api.allegro.pl/sale/product-offers/{offer_id}"
        response1 = requests.get(url1, headers=headers, timeout=10)
        if response1.status_code != 200:
            return ""
        
        data1 = response1.json()
        product_set = data1.get("productSet", [])
        if not product_set:
            return ""
        
        product_id = product_set[0]["product"]["id"]
        
        url2 = f"https://api.allegro.pl/sale/products/{product_id}"
        response2 = requests.get(url2, headers=headers, timeout=10)
        if response2.status_code != 200:
            return ""
        
        data2 = response2.json()
        parameters = data2.get("parameters", [])
        for param in parameters:
            if param.get("name") == "EAN (GTIN)":
                values = param.get("values", [])
                if values:
                    return values[0]
        return ""
    except Exception as e:
        current_app.logger.warning(f"Error getting EAN for offer {offer_id}: {e}")
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
            
            # Fetch EAN only for unlinked offers (where it's actually needed for linking)
            # Linked offers don't need EAN since they're already connected to products
            ean = offer.ean or ""
            if not ean and not (offer.product_size_id or offer.product_id):
                try:
                    ean = _get_ean_for_offer(offer.offer_id)
                    if ean:
                        offer.ean = ean
                        db.commit()
                except Exception as e:
                    ean = ""
            
            # Try to link by EAN if we have EAN but no product_size_id
            if ean and not offer.product_size_id:
                ps = db.query(ProductSize).filter(ProductSize.barcode == ean).first()
                if ps:
                    offer.product_size_id = ps.id
                    offer.product_id = ps.product_id
                    db.commit()
                    current_app.logger.info(f"Linked offer {offer.offer_id} to product_size {ps.id} by EAN {ean}")
                    # Update local vars for response
                    size = ps
                    product_for_label = ps.product
                    if product_for_label:
                        parts = [product_for_label.name]
                        if product_for_label.color:
                            parts.append(product_for_label.color)
                        label = " – ".join([" ".join(parts), ps.size])
            
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

        inventory = build_inventory_list(db)
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
    import time
    start_time = time.time()
    request_id = f"{int(start_time * 1000)}"
    current_app.logger.info(f"REQUEST START [{request_id}] /offers-and-prices")
    
    with get_session() as db:
        # Count statistics
        total_offers = db.query(AllegroOffer).filter(AllegroOffer.publication_status == 'ACTIVE').count()
        matched_offers = db.query(AllegroOffer).filter(
            AllegroOffer.publication_status == 'ACTIVE',
            (AllegroOffer.product_size_id.isnot(None)) | (AllegroOffer.product_id.isnot(None))
        ).count()
        
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
                "is_linked": bool(offer.product_size_id or offer.product_id),
            }
            
            # Fetch EAN only for unlinked offers (where it's actually needed)
            ean_value = offer.ean or ""
            if not ean_value and not (offer.product_size_id or offer.product_id):
                try:
                    ean_value = _get_ean_for_offer(offer.offer_id)
                    if ean_value:
                        offer.ean = ean_value
                        db.commit()
                except Exception as e:
                    pass
            offer_data["ean"] = ean_value
            offers_data.append(offer_data)

        # Build inventory for dropdown
        inventory = build_inventory_list(db)

    elapsed = time.time() - start_time
    current_app.logger.info(f"REQUEST END [{request_id}] /offers-and-prices - took {elapsed:.2f}s, {len(offers_data)} offers")
    
    response = make_response(render_template(
        "allegro/offers_and_prices.html",
        offers=offers_data,
        inventory=inventory,
        total_offers=total_offers,
        matched_offers=matched_offers,
    ))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response



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


# Import z nowego serwisu dla kompatybilnosci wstecznej
from .services.price_checker import build_price_checks, PriceCheckerService, DebugContext


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

    record_debug("Zadany format odpowiedzi", "json" if wants_json else "html")

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
