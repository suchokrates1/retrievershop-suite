import re


def _sales_keys():
    return [
        "COMMISSION_ALLEGRO",
        "ALERT_EMAIL",
        "SMTP_SERVER",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
    ]


def _extract_input(html, name):
    pattern = re.compile(
        rf"<input[^>]*name=\"{re.escape(name)}\"[^>]*>", re.IGNORECASE | re.DOTALL
    )
    match = pattern.search(html)
    assert match is not None, f"Input for {name} not found in HTML"
    return match.group(0)


def test_sales_settings_list_keys(app_mod, client, login, tmp_path):
    app_mod.ENV_PATH = tmp_path / ".env"
    resp = client.get("/sales/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    from magazyn.env_info import ENV_INFO
    for key in _sales_keys():
        label = ENV_INFO.get(key, (key, None))[0]
        assert label in html


def test_sales_settings_post_saves(
    app_mod, client, login, tmp_path, monkeypatch
):
    app_mod.ENV_PATH = tmp_path / ".env"
    reloaded = {"called": False}
    monkeypatch.setattr(
        app_mod.print_agent,
        "reload_config",
        lambda: reloaded.update(called=True),
    )
    values = {key: str(1.5 + i) for i, key in enumerate(_sales_keys())}
    resp = client.post("/sales/settings", data=values)
    assert resp.status_code == 302
    env_text = app_mod.ENV_PATH.read_text()
    for key, val in values.items():
        assert f"{key}={val}" in env_text
    assert reloaded["called"] is True


def test_sales_password_fields_render_as_password(app_mod, client, login, tmp_path):
    app_mod.ENV_PATH = tmp_path / ".env"
    resp = client.get("/sales/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    smtp_password = _extract_input(html, "SMTP_PASSWORD")
    assert "type=\"password\"" in smtp_password.lower()
