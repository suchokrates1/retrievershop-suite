import importlib
import sys
from collections import OrderedDict
from dotenv import load_dotenv

import magazyn.db as db_mod


def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "settings.db"))
    import werkzeug
    monkeypatch.setattr(werkzeug, "__version__", "0", raising=False)
    init = importlib.import_module("magazyn.__init__")
    importlib.reload(init)
    monkeypatch.setitem(sys.modules, "__init__", init)
    pa = importlib.import_module("magazyn.print_agent")
    monkeypatch.setitem(sys.modules, "print_agent", pa)
    monkeypatch.setattr(pa, "start_agent_thread", lambda: None)
    monkeypatch.setattr(pa, "ensure_db_init", lambda: None)
    monkeypatch.setattr(pa, "validate_env", lambda: None)
    import magazyn.app as app_mod
    importlib.reload(app_mod)
    from sqlalchemy.orm import sessionmaker
    db_mod.SessionLocal = sessionmaker(bind=db_mod.engine, autoflush=False, expire_on_commit=False)
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    # use temp env file
    app_mod.ENV_PATH = tmp_path / ".env"
    return app_mod


def login(client):
    with client.session_transaction() as sess:
        sess["username"] = "tester"


def test_settings_list_all_keys(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    login(client)
    resp = client.get("/settings")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    for key in app_mod.load_settings().keys():
        assert key in text


def test_settings_post_saves_and_reloads(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    reloaded = {"called": False}
    monkeypatch.setattr(app_mod.print_agent, "reload_config", lambda: reloaded.update(called=True))
    client = app_mod.app.test_client()
    login(client)
    values = {k: f"val{i}" for i, k in enumerate(app_mod.load_settings().keys())}
    resp = client.post("/settings", data=values)
    assert resp.status_code == 302
    env_text = app_mod.ENV_PATH.read_text()
    assert "API_TOKEN=val0" in env_text
    assert reloaded["called"] is True


def test_env_updates_persist_and_reload(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    login(client)

    monkeypatch.setattr(
        app_mod.print_agent,
        "load_dotenv",
        lambda override=True: load_dotenv(app_mod.ENV_PATH, override=override),
    )

    values = app_mod.load_settings()
    values["API_TOKEN"] = "v0"
    client.post("/settings", data=values)
    assert "API_TOKEN=v0" in app_mod.ENV_PATH.read_text()
    assert app_mod.print_agent.API_TOKEN == "v0"

    new_text = app_mod.ENV_PATH.read_text().replace("API_TOKEN=v0", "API_TOKEN=new0")
    app_mod.ENV_PATH.write_text(new_text)
    app_mod.print_agent.reload_config()
    assert app_mod.print_agent.API_TOKEN == "new0"

    pa = importlib.reload(app_mod.print_agent)
    assert pa.API_TOKEN == "new0"


def test_extra_keys_display_and_save(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    # create env file with an additional key
    app_mod.ENV_PATH.write_text("EXTRA_KEY=foo\n")

    client = app_mod.app.test_client()
    login(client)

    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "EXTRA_KEY" in html

    values = app_mod.load_settings()
    assert values.get("EXTRA_KEY") == "foo"
    values["EXTRA_KEY"] = "bar"
    client.post("/settings", data=values)
    env_lines = app_mod.ENV_PATH.read_text().strip().splitlines()
    assert env_lines[-1] == "EXTRA_KEY=bar"
    assert "EXTRA_KEY" in app_mod.load_settings()


def test_missing_example_file(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    app_mod.EXAMPLE_PATH = tmp_path / "no.env.example"

    client = app_mod.app.test_client()
    login(client)

    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "plik .env.example" in html.lower()

    with app_mod.app.test_request_context():
        assert app_mod.load_settings() == OrderedDict()

