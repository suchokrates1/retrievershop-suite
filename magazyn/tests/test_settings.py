import importlib
from collections import OrderedDict
from dotenv import load_dotenv

import magazyn.config as cfg


def test_settings_list_all_keys(app_mod, client, login, tmp_path):
    app_mod.ENV_PATH = tmp_path / ".env"
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


def test_settings_post_saves_and_reloads(
    app_mod, client, login, tmp_path, monkeypatch
):
    app_mod.ENV_PATH = tmp_path / ".env"
    reloaded = {"called": False}
    monkeypatch.setattr(
        app_mod.print_agent,
        "reload_config",
        lambda: reloaded.update(called=True),
    )
    values = {k: f"val{i}" for i, k in enumerate(app_mod.load_settings().keys())}
    from magazyn.sales import _sales_keys
    for skey in _sales_keys(values):
        values.pop(skey)
    values["QUIET_HOURS_START"] = "10:00"
    values["QUIET_HOURS_END"] = "22:00"
    resp = client.post("/settings", data=values)
    assert resp.status_code == 302
    env_text = app_mod.ENV_PATH.read_text()
    assert "API_TOKEN=val0" in env_text
    assert reloaded["called"] is True


def test_env_updates_persist_and_reload(
    app_mod, client, login, tmp_path, monkeypatch
):
    app_mod.ENV_PATH = tmp_path / ".env"

    original_load = cfg.load_config

    def reload_cfg():
        load_dotenv(app_mod.ENV_PATH, override=True)
        return original_load()

    monkeypatch.setattr(cfg, "load_config", reload_cfg)
    monkeypatch.setattr(app_mod.print_agent, "load_config", reload_cfg)

    values = app_mod.load_settings()
    values["API_TOKEN"] = "v0"
    client.post("/settings", data=values)
    assert "API_TOKEN=v0" in app_mod.ENV_PATH.read_text()
    assert app_mod.print_agent.API_TOKEN == "v0"

    new_text = app_mod.ENV_PATH.read_text().replace(
        "API_TOKEN=v0", "API_TOKEN=new0"
    )
    app_mod.ENV_PATH.write_text(new_text)
    app_mod.print_agent.reload_config()
    assert app_mod.print_agent.API_TOKEN == "new0"
    cfg.settings = app_mod.print_agent.settings

    pa = importlib.reload(app_mod.print_agent)
    assert pa.API_TOKEN == "new0"


def test_extra_keys_display_and_save(
    app_mod, client, login, tmp_path, monkeypatch
):
    app_mod.ENV_PATH = tmp_path / ".env"
    # create env file with an additional key
    app_mod.ENV_PATH.write_text("EXTRA_KEY=foo\n")

    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    from magazyn.env_info import ENV_INFO
    label = ENV_INFO.get("EXTRA_KEY", ("EXTRA_KEY", None))[0]
    assert label in html

    values = app_mod.load_settings()
    assert values.get("EXTRA_KEY") == "foo"
    values["EXTRA_KEY"] = "bar"
    client.post("/settings", data=values)
    env_lines = app_mod.ENV_PATH.read_text().strip().splitlines()
    assert env_lines[-1] == "EXTRA_KEY=bar"
    assert "EXTRA_KEY" in app_mod.load_settings()


def test_missing_example_file(app_mod, client, login, tmp_path, monkeypatch):
    app_mod.ENV_PATH = tmp_path / ".env"
    app_mod.EXAMPLE_PATH = tmp_path / "no.env.example"

    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "plik .env.example" in html.lower()

    with app_mod.app.test_request_context():
        assert app_mod.load_settings() == OrderedDict()
