from decimal import Decimal

import pytest
from requests.exceptions import HTTPError

from magazyn import allegro_api
from magazyn.metrics import (
    ALLEGRO_API_ERRORS_TOTAL,
    ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS,
    ALLEGRO_API_RETRIES_TOTAL,
)


class DummyResponse:
    def __init__(self, status_code, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if 400 <= self.status_code:
            raise HTTPError(response=self)

    def json(self):
        return self._json


def test_fetch_offers_retries_on_rate_limit(monkeypatch):
    calls = []
    sleeps = []
    responses = [
        DummyResponse(429, headers={"Retry-After": "0.5"}),
        DummyResponse(200, json_data={"offers": []}, headers={"X-RateLimit-Remaining": "1"}),
    ]

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    monkeypatch.setattr("magazyn.allegro_api.requests.get", fake_get)
    monkeypatch.setattr("magazyn.allegro_api.time.sleep", lambda value: sleeps.append(value))

    error_metric = ALLEGRO_API_ERRORS_TOTAL.labels(endpoint="offers", status="429")
    retry_metric = ALLEGRO_API_RETRIES_TOTAL.labels(endpoint="offers")
    sleep_metric = ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS.labels(endpoint="offers")
    before_error = error_metric._value.get()
    before_retry = retry_metric._value.get()
    before_sleep = sleep_metric._value.get()

    data = allegro_api.fetch_offers("token")

    assert data == {"offers": []}
    assert len(calls) == 2
    assert sleeps == [pytest.approx(0.5)]
    assert error_metric._value.get() == before_error + 1
    assert retry_metric._value.get() == before_retry + 1
    assert sleep_metric._value.get() == pytest.approx(before_sleep + 0.5)


def test_fetch_product_listing_retries_and_preserves_headers(monkeypatch):
    calls = []
    sleeps = []
    responses = [
        DummyResponse(503, headers={"Retry-After": "1"}),
        DummyResponse(
            200,
            json_data={
                "items": {
                    "promoted": [],
                    "regular": [
                        {
                            "id": "C1",
                            "seller": {"id": "competitor"},
                            "sellingMode": {"price": {"amount": "13.00"}},
                        }
                    ],
                }
            },
        ),
    ]

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    monkeypatch.setenv("ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.delenv("ALLEGRO_REFRESH_TOKEN", raising=False)
    monkeypatch.setattr("magazyn.allegro_api.requests.get", fake_get)
    monkeypatch.setattr("magazyn.allegro_api.time.sleep", lambda value: sleeps.append(value))

    retry_metric = ALLEGRO_API_RETRIES_TOTAL.labels(endpoint="listing")
    before_retry = retry_metric._value.get()

    items = allegro_api.fetch_product_listing("1234567890123")

    assert len(items) == 1
    assert Decimal(items[0]["sellingMode"]["price"]["amount"]) == Decimal("13.00")
    assert len(calls) == 2
    assert sleeps == [pytest.approx(1.0)]
    assert retry_metric._value.get() == before_retry + 1
