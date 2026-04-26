"""Bezpieczny wewnetrzny proxy do Allegro i wFirma API."""

from __future__ import annotations

from functools import partial
from typing import Any

import requests
from flask import Blueprint, jsonify, request
from flask_wtf.csrf import generate_csrf

from .auth import login_required
from .allegro_api.core import API_BASE_URL, _extract_allegro_error_details, _request_with_retry
from .allegro_api.tokens import get_allegro_token as _get_allegro_token, refresh_allegro_token as _refresh_allegro_token
from .wfirma_api.client import WFirmaClient, WFirmaError


bp = Blueprint("integration_proxy", __name__)

ALLEGRO_ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE"}
ALLEGRO_ALLOWED_PREFIXES = (
    "/order/",
    "/shipment-management/",
    "/billing/",
    "/sale/",
)
WFIRMA_ALLOWED_METHODS = {"GET", "POST"}
WFIRMA_ALLOWED_PREFIXES = (
    "invoices/",
    "contractors/",
    "goods/",
    "warehouse/",
    "payments/",
)
PROXY_RESPONSE_HEADERS = (
    "Content-Type",
    "Retry-After",
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
)


def _bad_request(message: str, status_code: int = 400):
    return jsonify({"ok": False, "error": message}), status_code


def _normalize_json_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("Oczekiwano obiektu JSON w body zadania")
    return payload


def _validate_allegro_request(method: str, path: str) -> tuple[str, str]:
    normalized_method = (method or "GET").upper()
    normalized_path = (path or "").strip()

    if normalized_method not in ALLEGRO_ALLOWED_METHODS:
        raise ValueError("Niedozwolona metoda Allegro")
    if not normalized_path.startswith("/"):
        raise ValueError("Sciezka Allegro musi zaczynac sie od '/'")
    if "://" in normalized_path or "?" in normalized_path:
        raise ValueError("Podaj sama sciezke Allegro bez hosta i query string")
    if not normalized_path.startswith(ALLEGRO_ALLOWED_PREFIXES):
        raise ValueError("Sciezka Allegro nie jest na allowliscie")

    return normalized_method, normalized_path


def _validate_wfirma_request(method: str, action: str) -> tuple[str, str]:
    normalized_method = (method or "POST").upper()
    normalized_action = (action or "").strip().lstrip("/")

    if normalized_method not in WFIRMA_ALLOWED_METHODS:
        raise ValueError("Niedozwolona metoda wFirma")
    if not normalized_action:
        raise ValueError("Brak akcji wFirma")
    if "://" in normalized_action or "?" in normalized_action:
        raise ValueError("Podaj sama akcje wFirma bez hosta i query string")
    if not normalized_action.startswith(WFIRMA_ALLOWED_PREFIXES):
        raise ValueError("Akcja wFirma nie jest na allowliscie")

    return normalized_method, normalized_action


def _serialize_response(response) -> dict[str, Any]:
    headers = {
        key: value
        for key, value in response.headers.items()
        if key in PROXY_RESPONSE_HEADERS
    }

    try:
        data = response.json()
    except ValueError:
        data = response.text[:5000]

    return {
        "ok": True,
        "status_code": response.status_code,
        "headers": headers,
        "data": data,
    }


def execute_allegro_proxy_request(
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    normalized_method, normalized_path = _validate_allegro_request(method, path)
    token, refresh = _get_allegro_token()
    url = f"{API_BASE_URL}{normalized_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    if body is not None:
        headers["Content-Type"] = "application/vnd.allegro.public.v1+json"

    request_callable = partial(requests.request, normalized_method)
    refreshed = False

    while True:
        try:
            response = _request_with_retry(
                request_callable,
                url,
                endpoint=f"proxy:{normalized_path.split('/', 2)[1]}",
                headers=headers,
                params=params,
                json=body,
            )
            return _serialize_response(response)
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (401, 403) and not refreshed and refresh:
                refreshed = True
                new_token = _refresh_allegro_token(refresh)
                headers["Authorization"] = f"Bearer {new_token}"
                continue

            details = _extract_allegro_error_details(getattr(exc, "response", None))
            raise RuntimeError(details.get("error_message") or str(exc)) from exc


def execute_wfirma_proxy_request(
    *,
    method: str,
    action: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_method, normalized_action = _validate_wfirma_request(method, action)
    client = WFirmaClient.from_settings()

    try:
        data = client.request(normalized_action, data=body, method=normalized_method)
    except WFirmaError as exc:
        raise RuntimeError(str(exc)) from exc

    return {
        "ok": True,
        "status_code": 200,
        "headers": {},
        "data": data,
    }


@bp.route("/api/integrations/proxy/config", methods=["GET"])
@login_required
def proxy_config():
    return jsonify(
        {
            "ok": True,
            "csrf_token": generate_csrf(),
            "allegro": {
                "methods": sorted(ALLEGRO_ALLOWED_METHODS),
                "prefixes": list(ALLEGRO_ALLOWED_PREFIXES),
            },
            "wfirma": {
                "methods": sorted(WFIRMA_ALLOWED_METHODS),
                "prefixes": list(WFIRMA_ALLOWED_PREFIXES),
            },
        }
    )


@bp.route("/api/integrations/proxy/allegro", methods=["POST"])
@login_required
def allegro_proxy():
    try:
        payload = _normalize_json_payload()
        result = execute_allegro_proxy_request(
            method=payload.get("method", "GET"),
            path=payload.get("path", ""),
            params=payload.get("params"),
            body=payload.get("body"),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    except RuntimeError as exc:
        return _bad_request(str(exc), 502)

    return jsonify(result)


@bp.route("/api/integrations/proxy/wfirma", methods=["POST"])
@login_required
def wfirma_proxy():
    try:
        payload = _normalize_json_payload()
        result = execute_wfirma_proxy_request(
            method=payload.get("method", "POST"),
            action=payload.get("action", ""),
            body=payload.get("body"),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    except RuntimeError as exc:
        return _bad_request(str(exc), 502)

    return jsonify(result)