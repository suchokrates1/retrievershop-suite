import importlib
import re
from urllib.parse import parse_qs, urlparse

import magazyn.config as cfg
from magazyn.settings_store import settings_store


def _extract_input(html, name):
    pattern = re.compile(
        rf"<input[^>]*name=\"{re.escape(name)}\"[^>]*>", re.IGNORECASE | re.DOTALL
    )
    match = pattern.search(html)
    assert match is not None, f"Input for {name} not found in HTML"
    return match.group(0)


def test_settings_list_all_keys(app_mod, client, login):
    settings_store.reload()
    resp = client.get("/settings")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    values = app_mod.load_settings()
    from magazyn.sales import _sales_keys
    from magazyn.env_info import ENV_INFO

    sales_keys = _sales_keys(values)
    for key in values.keys():
        label = ENV_INFO.get(key, (key, None))[0]
        if key in sales_keys:
            assert label not in text
        else:
            assert label in text


def test_store_populates_database_when_empty(app_mod):
    from magazyn import DB_PATH
    from magazyn.db import sqlite_connect

    with sqlite_connect(DB_PATH) as conn:
        conn.execute("DELETE FROM app_settings")
        conn.commit()

    settings_store.reload()
    values = settings_store.as_ordered_dict(include_hidden=True)

    assert values


def test_sensitive_tokens_render_as_password(app_mod, client, login):
    settings_store.reload()
    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for key in [
        "API_TOKEN",
        "PAGE_ACCESS_TOKEN",
        "ALLEGRO_CLIENT_SECRET",
        "ALLEGRO_ACCESS_TOKEN",
        "ALLEGRO_REFRESH_TOKEN",
    ]:
        field_html = _extract_input(html, key)
        assert "type=\"password\"" in field_html.lower()


def test_settings_post_updates_store(app_mod, client, login, monkeypatch):
    reloaded = {"called": False}
    monkeypatch.setattr(
        app_mod.print_agent,
        "reload_config",
        lambda: reloaded.update(called=True),
    )
    values = app_mod.load_settings(include_hidden=True)
    from magazyn.sales import _sales_keys

    for skey in _sales_keys(values):
        values.pop(skey, None)
    values["QUIET_HOURS_START"] = "10:00"
    values["QUIET_HOURS_END"] = "22:00"
    values["API_TOKEN"] = "val0"
    resp = client.post("/settings", data=values)
    assert resp.status_code == 302
    stored = settings_store.as_ordered_dict(include_hidden=True)
    assert stored["API_TOKEN"] == "val0"
    assert reloaded["called"] is True


def test_weekly_reports_setting_saved(app_mod, client, login):
    values = app_mod.load_settings(include_hidden=True)
    assert "ENABLE_WEEKLY_REPORTS" in values
    from magazyn.sales import _sales_keys

    for skey in _sales_keys(values):
        values.pop(skey, None)
    values["ENABLE_WEEKLY_REPORTS"] = "0"
    values["QUIET_HOURS_START"] = "10:00"
    values["QUIET_HOURS_END"] = "22:00"
    resp = client.post("/settings", data=values)
    assert resp.status_code == 302
    stored = settings_store.as_ordered_dict()
    assert stored["ENABLE_WEEKLY_REPORTS"] == "0"


def test_settings_reload_updates_print_agent(app_mod, client, login, monkeypatch):
    values = app_mod.load_settings(include_hidden=True)
    values["API_TOKEN"] = "v0"
    from magazyn.sales import _sales_keys

    for skey in _sales_keys(values):
        values.pop(skey, None)
    values["QUIET_HOURS_START"] = "10:00"
    values["QUIET_HOURS_END"] = "22:00"
    client.post("/settings", data=values)
    assert settings_store.settings.API_TOKEN == "v0"

    settings_store.update({"API_TOKEN": "new0"})
    app_mod.print_agent.reload_config()
    assert app_mod.print_agent.API_TOKEN == "new0"
    cfg.settings = app_mod.print_agent.settings

    pa = importlib.reload(app_mod.print_agent)
    assert pa.API_TOKEN == "new0"


def test_extra_keys_display_and_save(app_mod, client, login, monkeypatch):
    settings_store.update({"EXTRA_KEY": "foo"})

    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    from magazyn.env_info import ENV_INFO

    label = ENV_INFO.get("EXTRA_KEY", ("EXTRA_KEY", None))[0]
    assert label in html
    extra_field = _extract_input(html, "EXTRA_KEY")
    assert "type=\"password\"" in extra_field.lower()

    values = app_mod.load_settings(include_hidden=True)
    values["EXTRA_KEY"] = "bar"
    from magazyn.sales import _sales_keys

    for skey in _sales_keys(values):
        values.pop(skey, None)
    values["QUIET_HOURS_START"] = "10:00"
    values["QUIET_HOURS_END"] = "22:00"
    client.post("/settings", data=values)
    stored = settings_store.as_ordered_dict(include_hidden=True)
    assert stored["EXTRA_KEY"] == "bar"


def test_missing_example_file(app_mod, client, login, tmp_path, monkeypatch):
    from magazyn import settings_io

    monkeypatch.setattr(settings_io, "EXAMPLE_PATH", tmp_path / "no.env.example")
    settings_store.reload()

    resp = client.get("/settings")
    assert resp.status_code == 200

    from flask import get_flashed_messages

    with app_mod.app.test_request_context():
        values = app_mod.load_settings()
        flashes = get_flashed_messages()
        assert any("plik .env.example" in msg.lower() for msg in flashes)
        assert values  # fallback still provides stored values


def test_settings_page_shows_allegro_authorize_button(app_mod, client, login):
    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Połącz z Allegro" in html
    assert "action=\"/allegro/authorize\"" in html


def test_allegro_authorize_redirects_to_provider(app_mod, client, login):
    settings_store.update(
        {
            "ALLEGRO_CLIENT_ID": "client-123",
            "ALLEGRO_REDIRECT_URI": "https://example.com/callback",
        }
    )

    resp = client.post("/allegro/authorize")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith(app_mod.ALLEGRO_AUTHORIZATION_URL)

    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    assert params["client_id"] == ["client-123"]
    assert params["redirect_uri"] == ["https://example.com/callback"]
    assert params["response_type"] == ["code"]
    state = params.get("state", [""])[0]
    assert state

    with client.session_transaction() as sess:
        assert sess.get("allegro_oauth_state") == state
