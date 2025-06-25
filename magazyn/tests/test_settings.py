import importlib
import sys
from sqlalchemy import text

import magazyn.db as db_mod


def setup_app(tmp_path, monkeypatch):
    db_file = tmp_path / "settings.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
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
    db_mod.SessionLocal = sessionmaker(
        bind=db_mod.engine, autoflush=False, expire_on_commit=False
    )
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod


def login(client):
    with client.session_transaction() as sess:
        sess["username"] = "tester"


def test_settings_route_creates_table(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    login(client)
    resp = client.get("/settings")
    assert resp.status_code == 200
    with db_mod.get_db_connection() as db:
        row = db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
        ).fetchone()
        assert row is not None

