import json
import secrets
from time import time
from typing import Optional
from urllib.parse import urlencode

from flask import (
    Blueprint,
    current_app,
    make_response,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)

from .db import get_session
from .models.allegro import AllegroOffer
from .models.products import Product, ProductSize
from .allegro_sync import sync_offers
from .settings_store import SettingsPersistenceError, settings_store
from .env_tokens import update_allegro_tokens
from .print_agent import agent
from .auth import login_required
from .services.allegro_offer_views import (
    build_offers_and_prices_context,
    build_offers_context,
    get_ean_for_offer,
    new_request_id,
)
from . import allegro_api
from requests.exceptions import HTTPError, RequestException

ALLEGRO_AUTHORIZATION_URL = "https://allegro.pl/auth/oauth/authorize"

bp = Blueprint("allegro", __name__)

SENSITIVE_DEBUG_KEYS = {
    "access_token",
    "refresh_token",
    "code",
    "client_secret",
    "ALLEGRO_CLIENT_SECRET",
}


def _redact_debug_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key) in SENSITIVE_DEBUG_KEYS else _redact_debug_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_debug_value(item) for item in value]
    return value


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
    steps.append({"label": label, "value": _format_debug_value(_redact_debug_value(value))})


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


def _process_oauth_response() -> dict[str, object]:
    debug_steps: list[dict[str, str]] = []

    # Loguj wszystkie parametry z callbacka (w tym bledy od Allegro)
    all_args = dict(request.args)
    _record_debug_step(debug_steps, "Wszystkie parametry callbacka", all_args)
    current_app.logger.info(
        "Allegro OAuth callback args: %s",
        _redact_debug_value(all_args),
    )
    
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
    _record_debug_step(debug_steps, "Kod autoryzacyjny Allegro", {"code": code})
    if not code:
        current_app.logger.warning("Allegro OAuth callback without authorization code")
        message = "Brak kodu autoryzacyjnego w odpowiedzi Allegro."
        return {"ok": False, "message": message, "debug_steps": debug_steps}

    client_id = settings_store.get("ALLEGRO_CLIENT_ID")
    client_secret = settings_store.get("ALLEGRO_CLIENT_SECRET")
    redirect_uri = settings_store.get("ALLEGRO_REDIRECT_URI")
    _record_debug_step(debug_steps, "ALLEGRO_CLIENT_ID", client_id)
    _record_debug_step(debug_steps, "ALLEGRO_CLIENT_SECRET", {"ALLEGRO_CLIENT_SECRET": client_secret})
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
    _record_debug_step(debug_steps, "Access token", {"access_token": access_token})
    _record_debug_step(debug_steps, "Refresh token", {"refresh_token": refresh_token})
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
        flash("Uzupełnij konfigurację Allegro, aby rozpocząć autoryzację.", "warning")
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
        flash(message, "success" if result.get("ok") else "error")
    return redirect(url_for("settings_page"))


@bp.get("/allegro")
@login_required
def allegro_oauth_debug():
    result = _process_oauth_response()
    if message := result.get("message"):
        flash(message, "success" if result.get("ok") else "error")
    return redirect(url_for("settings_page"))


def _get_ean_for_offer(offer_id: str) -> str:
    """Get EAN for an offer from Allegro API."""
    return get_ean_for_offer(offer_id, log=current_app.logger)


@bp.route("/allegro/offers")
@login_required
def offers():
    context = build_offers_context(
        fetch_ean_for_offer=_get_ean_for_offer,
        log=current_app.logger,
    )
    response = make_response(render_template(
        "allegro/offers.html",
        **context,
    ))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@bp.route("/offers-and-prices")
@login_required
def offers_and_prices():
    start_time, request_id = new_request_id()
    current_app.logger.info(f"REQUEST START [{request_id}] /offers-and-prices")
    context = build_offers_and_prices_context(
        request.args,
        fetch_ean_for_offer=_get_ean_for_offer,
        log=current_app.logger,
    )

    elapsed = time() - start_time
    current_app.logger.info(
        "REQUEST END [%s] /offers-and-prices - took %.2fs, %s offers",
        request_id,
        elapsed,
        context.pop("offers_count"),
    )

    response = make_response(render_template(
        "allegro/offers_and_prices.html",
        **context,
    ))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
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
            ),
            "success",
        )
    except Exception as e:
        flash(f"Błąd synchronizacji ofert: {e}", "error")
    return redirect(url_for("allegro.offers"))


@bp.route("/allegro/link/<offer_id>", methods=["GET", "POST"])
@login_required
def link_offer(offer_id):
    with get_session() as db:
        offer = db.query(AllegroOffer).filter_by(offer_id=offer_id).first()
        if not offer:
            flash("Nie znaleziono aukcji", "error")
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
                    flash("Powiązano ofertę z pozycją magazynową", "success")
                else:
                    flash("Nie znaleziono rozmiaru produktu o podanym ID", "error")
            elif product_id:
                product = db.query(Product).filter_by(id=product_id).first()
                if product:
                    offer.product_id = product.id
                    offer.product_size_id = None
                    flash("Powiązano aukcję z produktem", "success")
                else:
                    flash("Nie znaleziono produktu o podanym ID", "error")
            else:
                offer.product_size_id = None
                offer.product_id = None
                flash("Usunięto powiązanie z magazynem", "info")
            return redirect(url_for("allegro.offers"))

        offer_data = {
            "offer_id": offer.offer_id,
            "title": offer.title,
            "price": offer.price,
            "product_id": offer.product_id or "",
            "product_size_id": offer.product_size_id or "",
        }
    return render_template("allegro/link.html", offer=offer_data)
