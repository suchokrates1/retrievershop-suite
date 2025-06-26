import importlib
import sys

from werkzeug.security import generate_password_hash
from magazyn.models import User


def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", ":memory:")
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
    import magazyn.db as db_mod
    from sqlalchemy.orm import sessionmaker
    db_mod.SessionLocal = sessionmaker(bind=db_mod.engine, autoflush=False, expire_on_commit=False)
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    app_mod.reset_db()
    return app_mod


def setup_app_default_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", ":memory:")
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
    import magazyn.db as db_mod
    from sqlalchemy.orm import sessionmaker
    db_mod.SessionLocal = sessionmaker(bind=db_mod.engine, autoflush=False)
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    app_mod.reset_db()
    return app_mod


def test_login_route_authenticates_user(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    hashed = generate_password_hash("secret")
    with app_mod.get_session() as db:
        db.add(User(username="tester", password=hashed))

    resp = client.post("/login", data={"username": "tester", "password": "secret"})
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["username"] == "tester"


def test_login_default_session_expiry(tmp_path, monkeypatch):
    app_mod = setup_app_default_session(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    hashed = generate_password_hash("secret")
    with app_mod.get_session() as db:
        db.add(User(username="tester", password=hashed))

    resp = client.post("/login", data={"username": "tester", "password": "secret"})
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["username"] == "tester"
