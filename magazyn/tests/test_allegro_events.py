"""Testy modulu allegro_api/events.py - polling dziennika zdarzen Allegro."""
import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from requests.exceptions import HTTPError

from magazyn.allegro_api.events import (
    fetch_order_events,
    fetch_event_stats,
    ACTIONABLE_EVENT_TYPES,
)


def _mock_response(data, status_code=200):
    """Tworzy mock odpowiedzi HTTP."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.headers = {}
    resp.raise_for_status.return_value = None
    return resp


def _mock_error_response(status_code=401):
    """Tworzy mock blednej odpowiedzi HTTP."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.json.return_value = {"errors": [{"code": "UNAUTHORIZED", "message": "Token expired"}]}
    error = HTTPError(response=resp)
    resp.raise_for_status.side_effect = error
    return resp


# --- fetch_order_events ---


@patch("magazyn.allegro_api.events._get_allegro_token", return_value=("test_token", "test_refresh"))
@patch("magazyn.allegro_api.events._request_with_retry")
def test_fetch_order_events_basic(mock_request, mock_token):
    """Podstawowe wywolanie bez parametrow."""
    events_data = {
        "events": [
            {
                "id": "event-001",
                "type": "READY_FOR_PROCESSING",
                "occurredAt": "2026-03-24T10:00:00Z",
                "order": {"checkoutForm": {"id": "cf-uuid-1"}},
            }
        ]
    }
    mock_request.return_value = _mock_response(events_data)

    result = fetch_order_events()

    assert result == events_data
    assert len(result["events"]) == 1
    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    assert call_kwargs.kwargs["params"]["limit"] == 1000


@patch("magazyn.allegro_api.events._get_allegro_token", return_value=("test_token", "test_refresh"))
@patch("magazyn.allegro_api.events._request_with_retry")
def test_fetch_order_events_with_from_id(mock_request, mock_token):
    """Wywolanie z parametrem from_event_id (inkrementalne)."""
    mock_request.return_value = _mock_response({"events": []})

    fetch_order_events(from_event_id="event-100")

    call_kwargs = mock_request.call_args
    assert call_kwargs.kwargs["params"]["from"] == "event-100"


@patch("magazyn.allegro_api.events._get_allegro_token", return_value=("test_token", "test_refresh"))
@patch("magazyn.allegro_api.events._request_with_retry")
def test_fetch_order_events_with_types_filter(mock_request, mock_token):
    """Wywolanie z filtrem typow zdarzen."""
    mock_request.return_value = _mock_response({"events": []})

    fetch_order_events(event_types=["READY_FOR_PROCESSING", "BUYER_CANCELLED"])

    call_kwargs = mock_request.call_args
    assert call_kwargs.kwargs["params"]["type"] == ["READY_FOR_PROCESSING", "BUYER_CANCELLED"]


@patch("magazyn.allegro_api.events._get_allegro_token", return_value=("test_token", "test_refresh"))
@patch("magazyn.allegro_api.events._request_with_retry")
def test_fetch_order_events_limit_clamped(mock_request, mock_token):
    """Limit jest ograniczany do zakresu 1-1000."""
    mock_request.return_value = _mock_response({"events": []})

    fetch_order_events(limit=5000)
    assert mock_request.call_args.kwargs["params"]["limit"] == 1000

    fetch_order_events(limit=0)
    assert mock_request.call_args.kwargs["params"]["limit"] == 1


@patch("magazyn.allegro_api.events._get_allegro_token", return_value=("test_token", "test_refresh"))
@patch("magazyn.allegro_api.events._request_with_retry")
@patch("magazyn.allegro_api.events._refresh_allegro_token", return_value="new_token")
def test_fetch_order_events_token_refresh(mock_refresh, mock_request, mock_token):
    """Automatyczne odswiezenie tokenu przy 401."""
    error_resp = _mock_error_response(401)
    ok_resp = _mock_response({"events": []})
    mock_request.side_effect = [
        HTTPError(response=error_resp),
        ok_resp,
    ]

    # Przy 401 side_effect rzuca HTTPError, ale nasz kod lapie i refreshuje
    # Potrzebujemy zasymulowac raise_for_status
    first_resp = MagicMock()
    first_resp.status_code = 401
    first_resp.headers = {}
    first_resp.json.return_value = {}
    exc = HTTPError(response=first_resp)
    exc.response = first_resp

    mock_request.side_effect = [exc, ok_resp]

    result = fetch_order_events()

    assert result == {"events": []}
    mock_refresh.assert_called_once_with("test_refresh")


# --- fetch_event_stats ---


@patch("magazyn.allegro_api.events._get_allegro_token", return_value=("test_token", "test_refresh"))
@patch("magazyn.allegro_api.events._request_with_retry")
def test_fetch_event_stats(mock_request, mock_token):
    """Pobranie statystyk zdarzen."""
    stats_data = {
        "latestEvent": {
            "id": "event-999",
            "occurredAt": "2026-03-24T12:00:00Z",
        }
    }
    mock_request.return_value = _mock_response(stats_data)

    result = fetch_event_stats()

    assert result["latestEvent"]["id"] == "event-999"
    call_args = mock_request.call_args
    assert "order/event-stats" in call_args.args[1]


# --- ACTIONABLE_EVENT_TYPES ---


def test_actionable_event_types():
    """Sprawdz ze kluczowe typy zdarzen sa w zbiorze."""
    assert "BOUGHT" in ACTIONABLE_EVENT_TYPES
    assert "FILLED_IN" in ACTIONABLE_EVENT_TYPES
    assert "READY_FOR_PROCESSING" in ACTIONABLE_EVENT_TYPES
    assert "BUYER_CANCELLED" in ACTIONABLE_EVENT_TYPES
    assert "AUTO_CANCELLED" in ACTIONABLE_EVENT_TYPES
    assert "FULFILLMENT_STATUS_CHANGED" in ACTIONABLE_EVENT_TYPES
