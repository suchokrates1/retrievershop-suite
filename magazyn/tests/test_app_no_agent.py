import importlib
import sys
import magazyn.config as cfg


def setup_app_missing_agent(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(cfg.settings, "DB_PATH", str(db_path))
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
    from magazyn.factory import create_app
    import magazyn.db as db_mod

    importlib.reload(db_mod)
    db_mod.configure_engine(cfg.settings.DB_PATH)
    from sqlalchemy.orm import sessionmaker

    db_mod.SessionLocal = sessionmaker(
        bind=db_mod.engine, autoflush=False
    )

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    app_mod.app = app
    app_mod.reset_db()
    return app_mod


def test_app_response_without_agent(tmp_path, monkeypatch):
    app_mod = setup_app_missing_agent(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200

import uuid

def test_discussions_page_loads_without_error(tmp_path, monkeypatch):
    app_mod = setup_app_missing_agent(tmp_path, monkeypatch)
    client = app_mod.app.test_client()
    with app_mod.app.app_context():
        with app_mod.get_session() as db:
            from magazyn.models import User, Thread, Message
            from werkzeug.security import generate_password_hash

            user = User(username='test', password=generate_password_hash('test'))
            db.add(user)
            thread = Thread(id=str(uuid.uuid4()), title="Test Thread", author="test", type="dyskusja")
            db.add(thread)
            message = Message(id=str(uuid.uuid4()), thread_id=thread.id, author="test", content="Test message")
            db.add(message)
            db.commit()

        with client:
            client.post('/login', data={'username': 'test', 'password': 'test'})
            resp = client.get("/discussions")
            assert resp.status_code == 200
            assert b"Test Thread" in resp.data
