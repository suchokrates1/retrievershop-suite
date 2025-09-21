import importlib
import sys
import pytest

import magazyn.config as cfg


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(cfg.settings, "DB_PATH", str(db_path))
    monkeypatch.setattr(cfg.settings, "COMMISSION_ALLEGRO", 10.0)
    import magazyn.sales as sales_mod

    importlib.reload(sales_mod)
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
    from magazyn.factory import create_app
    import magazyn.db as db_mod

    importlib.reload(db_mod)
    monkeypatch.setattr(db_mod, "apply_migrations", lambda: None)
    db_mod.configure_engine(cfg.settings.DB_PATH)
    from sqlalchemy.orm import sessionmaker

    db_mod.SessionLocal = sessionmaker(
        bind=db_mod.engine, autoflush=False, expire_on_commit=False
    )

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    app_mod.app = app
    app_mod.reset_db()
    return app_mod


@pytest.fixture
def client(app_mod):
    return app_mod.app.test_client()


@pytest.fixture
def login(client):
    with client.session_transaction() as sess:
        sess["username"] = "tester"
    yield
