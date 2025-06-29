import importlib
import sys
import magazyn.config as cfg


def setup_app_missing_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg.settings, "DB_PATH", ":memory:")
    monkeypatch.setattr(cfg.settings, "API_TOKEN", "")
    monkeypatch.setattr(cfg.settings, "PAGE_ACCESS_TOKEN", "")
    monkeypatch.setattr(cfg.settings, "RECIPIENT_ID", "")

    import werkzeug

    monkeypatch.setattr(werkzeug, "__version__", "0", raising=False)

    init = importlib.import_module("magazyn.__init__")
    importlib.reload(init)
    monkeypatch.setitem(sys.modules, "__init__", init)

    pa = importlib.import_module("magazyn.print_agent")
    pa = importlib.reload(pa)
    monkeypatch.setitem(sys.modules, "print_agent", pa)
    monkeypatch.setattr(pa, "start_agent_thread", lambda: None)
    monkeypatch.setattr(pa, "ensure_db_init", lambda: None)

    import magazyn.app as app_mod

    importlib.reload(app_mod)
    import magazyn.db as db_mod

    db_mod.configure_engine(cfg.settings.DB_PATH)
    from sqlalchemy.orm import sessionmaker

    db_mod.SessionLocal = sessionmaker(
        bind=db_mod.engine, autoflush=False, expire_on_commit=False
    )
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    app_mod.reset_db()
    return app_mod


def test_app_response_without_agent(tmp_path, monkeypatch):
    app_mod = setup_app_missing_agent(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200
