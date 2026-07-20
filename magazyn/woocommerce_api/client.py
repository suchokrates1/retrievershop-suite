"""HTTP klient WooCommerce REST (Basic Auth consumer key/secret)."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from ..settings_store import settings_store

logger = logging.getLogger(__name__)


class WooClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class WooClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        timeout: int = 45,
    ):
        self.base_url = (base_url or settings_store.get("WOO_URL") or "").rstrip("/") + "/"
        self.consumer_key = consumer_key or settings_store.get("WOO_CONSUMER_KEY") or ""
        self.consumer_secret = consumer_secret or settings_store.get("WOO_CONSUMER_SECRET") or ""
        self.timeout = timeout
        if not self.base_url or not self.consumer_key or not self.consumer_secret:
            raise WooClientError("Brak konfiguracji WooCommerce (WOO_URL / KEY / SECRET)")

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        response = requests.request(
            method,
            url,
            params=params,
            json=json,
            auth=(self.consumer_key, self.consumer_secret),
            timeout=self.timeout,
            headers={"User-Agent": "retrievershop-magazyn/woo"},
        )
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = response.text[:500]
            raise WooClientError(
                f"Woo API {method} {path} -> {response.status_code}: {payload}",
                status_code=response.status_code,
                payload=payload,
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> Any:
        return self.request("PUT", path, **kwargs)
