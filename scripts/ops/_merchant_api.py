"""Shared read/write helpers for Google Merchant API v1 operational scripts."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

sys.path.insert(0, os.path.expanduser("~/infrastructure"))
import bw_get as bw  # noqa: E402

OAUTH_ITEM = "Google OAuth Retriever Shop"
DEFAULT_MERCHANT_ID = "5415963608"
API_ROOT = "https://merchantapi.googleapis.com/products/v1"


def merchant_id() -> str:
    return bw.get_item(OAUTH_ITEM, "merchant_id") or DEFAULT_MERCHANT_ID


def access_token() -> str:
    body = urllib.parse.urlencode(
        {
            "client_id": bw.get_item(OAUTH_ITEM, "client_id"),
            "client_secret": bw.get_item(OAUTH_ITEM, "client_secret"),
            "refresh_token": bw.get_item(OAUTH_ITEM, "refresh_token"),
            "grant_type": "refresh_token",
        }
    ).encode()
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return json.loads(urllib.request.urlopen(request, timeout=30).read())["access_token"]


def request_json(
    method: str, url: str, access: str, data: bytes | None = None
) -> tuple[int, dict[str, Any] | str]:
    headers = {"Authorization": f"Bearer {access}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:2000]


def list_products(access: str, account: str) -> list[dict[str, Any]]:
    """Return all processed products, including attributes and validation issues."""
    products: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(100):
        query = {"pageSize": "1000"}
        if page_token:
            query["pageToken"] = page_token
        code, payload = request_json(
            "GET",
            f"{API_ROOT}/accounts/{account}/products?{urllib.parse.urlencode(query)}",
            access,
        )
        if code != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"Merchant API products.list failed: {code} {payload}")
        products.extend(payload.get("products") or [])
        page_token = payload.get("nextPageToken")
        if not page_token:
            return products
    raise RuntimeError("Merchant API pagination exceeded 100 pages")


def normalized_price(price: Any) -> dict[str, str] | None:
    """Convert Merchant API amountMicros price to the legacy audit representation."""
    if not isinstance(price, dict):
        return None
    micros = price.get("amountMicros")
    currency = price.get("currencyCode")
    if micros is None or not currency:
        return None
    value = Decimal(str(micros)) / Decimal("1000000")
    return {"value": format(value, "f"), "currency": str(currency)}


def issue_servability(severity: str | None) -> str:
    """Keep existing audit group labels while retaining the Merchant API severity."""
    return {
        "DISAPPROVED": "disapproved",
        "DEMOTED": "demoted",
        "NOT_IMPACTED": "unaffected",
    }.get(severity or "", (severity or "unknown").lower())


def product_input_name(product: dict[str, Any]) -> str | None:
    """Build the matching productInputs resource name for a processed product."""
    name = product.get("base64EncodedName") or product.get("name")
    if not isinstance(name, str) or "/products/" not in name:
        return None
    return name.replace("/products/", "/productInputs/", 1)
