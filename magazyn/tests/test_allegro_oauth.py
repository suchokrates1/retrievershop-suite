import json
from urllib.parse import parse_qs, urlparse

import pytest
from requests.exceptions import HTTPError

from magazyn import allegro_api
from magazyn.allegro import ALLEGRO_AUTHORIZATION_URL
from magazyn.settings_store import settings_store


@pytest.fixture
def allegro_oauth_config():
    original_values = {
        key: settings_store.get(key)
        for key in (
            "ALLEGRO_CLIENT_ID",
            "ALLEGRO_CLIENT_SECRET",
            "ALLEGRO_REDIRECT_URI",
            "ALLEGRO_ACCESS_TOKEN",
            "ALLEGRO_REFRESH_TOKEN",
            "ALLEGRO_TOKEN_EXPIRES_IN",
            "ALLEGRO_TOKEN_METADATA",
        )
    }
    settings_store.update(
        {
            "ALLEGRO_CLIENT_ID": "client-123",
            "ALLEGRO_CLIENT_SECRET": "secret-456",
            "ALLEGRO_REDIRECT_URI": "https://example.com/callback",
            "ALLEGRO_ACCESS_TOKEN": None,
            "ALLEGRO_REFRESH_TOKEN": None,
            "ALLEGRO_TOKEN_EXPIRES_IN": None,
            "ALLEGRO_TOKEN_METADATA": None,
        }
    )

    try:
        yield
    finally:
        cleanup = {
            key: value if value is not None else None
            for key, value in original_values.items()
        }
        settings_store.update(cleanup)
        settings_store.reload()


def _get_flashes(client):
    with client.session_transaction() as session:
        return session.get("_flashes") or []


def _start_authorization(client):
    response = client.post("/allegro/authorize")
    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.startswith(ALLEGRO_AUTHORIZATION_URL)
    params = parse_qs(urlparse(location).query)
    state = params.get("state", [""])[0]
    assert state
    return state


def test_full_oauth_flow(client, login, monkeypatch, allegro_oauth_config):
    state = _start_authorization(client)

    def fake_get_access_token(client_id, client_secret, code, redirect_uri=None):
        assert client_id == "client-123"
        assert client_secret == "secret-456"
        assert code == "auth-code"
        assert redirect_uri == "https://example.com/callback"
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "scope": "sale:offers",
            "token_type": "bearer",
        }

    monkeypatch.setattr(allegro_api, "get_access_token", fake_get_access_token)

    response = client.get(
        "/allegro/oauth/callback",
        query_string={"state": state, "code": "auth-code"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings")

    with client.session_transaction() as session:
        assert "allegro_oauth_state" not in session

    flashes = _get_flashes(client)
    assert any("sukcesem" in message.lower() for _, message in flashes)

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") == "access-token"
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") == "refresh-token"
    assert settings_store.get("ALLEGRO_TOKEN_EXPIRES_IN") == "3600"

    metadata_raw = settings_store.get("ALLEGRO_TOKEN_METADATA")
    assert metadata_raw
    metadata = json.loads(metadata_raw)
    assert metadata["scope"] == "sale:offers"
    assert metadata["token_type"] == "bearer"
    assert metadata["expires_in"] == 3600


def test_oauth_callback_state_mismatch(client, login, allegro_oauth_config):
    _start_authorization(client)

    response = client.get(
        "/allegro/oauth/callback",
        query_string={"state": "invalid", "code": "auth-code"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings")

    flashes = _get_flashes(client)
    assert any("state" in message.lower() for _, message in flashes)

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") is None


def test_oauth_callback_missing_code(client, login, allegro_oauth_config):
    state = _start_authorization(client)

    response = client.get(
        "/allegro/oauth/callback",
        query_string={"state": state},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings")

    flashes = _get_flashes(client)
    assert any("brak kodu" in message.lower() for _, message in flashes)

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") is None


def test_oauth_callback_handles_api_error(
    client, login, monkeypatch, allegro_oauth_config
):
    state = _start_authorization(client)

    class DummyResponse:
        status_code = 400

    def failing_get_access_token(*_, **__):
        raise HTTPError(response=DummyResponse())

    monkeypatch.setattr(allegro_api, "get_access_token", failing_get_access_token)

    response = client.get(
        "/allegro/oauth/callback",
        query_string={"state": state, "code": "auth-code"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings")

    flashes = _get_flashes(client)
    assert any("http status 400" in message.lower() for _, message in flashes)

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") is None

