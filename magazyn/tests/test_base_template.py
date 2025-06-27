import importlib
import sys
from magazyn.models import User
from werkzeug.security import generate_password_hash
import magazyn.config as cfg


def setup_app(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg.settings, "DB_PATH", ":memory:")
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


def login(client):
    with client.session_transaction() as sess:
        sess["username"] = "tester"


def test_nav_container_class(tmp_path, monkeypatch):
    app_mod = setup_app(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    hashed = generate_password_hash("secret")
    with app_mod.get_session() as db:
        db.add(User(username="tester", password=hashed))
    login(client)
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    import re
    nav_match = re.search(r"<nav[^>]*>(.*?)</nav>", html, re.S)
    assert nav_match, "nav section missing"
    nav_html = nav_match.group(1)
    assert "container-fluid" not in nav_html
    assert "class=\"container\"" in nav_html
