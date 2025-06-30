def _sales_keys():
    return [
        "DEFAULT_SHIPPING_ALLEGRO",
        "FREE_SHIPPING_THRESHOLD_ALLEGRO",
        "COMMISSION_ALLEGRO",
    ]


def test_sales_settings_list_keys(app_mod, client, login, tmp_path):
    app_mod.ENV_PATH = tmp_path / ".env"
    resp = client.get("/sales/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for key in _sales_keys():
        assert key in html


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


def test_thresholds_saved_and_displayed(app_mod, client, login):
    from magazyn.models import ShippingThreshold

    with app_mod.get_session() as db:
        db.add(ShippingThreshold(min_order_value=0.0, shipping_cost=10.0))

    resp = client.get("/sales/settings")
    assert resp.status_code == 200
    assert "10.00" in resp.get_data(as_text=True)

    data = {
        "threshold_min": ["0", "100"],
        "threshold_cost": ["8", "0"],
    }
    client.post("/sales/settings", data=data)

    with app_mod.get_session() as db:
        rows = db.query(ShippingThreshold).order_by(ShippingThreshold.min_order_value).all()
        assert len(rows) == 2
        assert rows[1].min_order_value == 100.0
