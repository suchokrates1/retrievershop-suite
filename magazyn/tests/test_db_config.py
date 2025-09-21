import sqlite3
from types import SimpleNamespace
from werkzeug.security import generate_password_hash

import magazyn.db as db
import magazyn.print_agent as pa
from magazyn.models import User


def test_reload_env_reconfigures_engine(tmp_path, monkeypatch):
    first = tmp_path / "first.db"
    monkeypatch.setattr(db, "apply_migrations", lambda: None)
    db.configure_engine(str(first))
    db.init_db()
    with db.get_session() as session:
        session.add(User(username="u1", password=generate_password_hash("p")))

    second = tmp_path / "second.db"
    new_settings = SimpleNamespace(**vars(pa.settings))
    new_settings.DB_PATH = str(second)
    monkeypatch.setattr(pa, "load_config", lambda: new_settings)

    pa.reload_config()

    db.init_db()
    with db.get_session() as session:
        session.add(User(username="u2", password=generate_password_hash("p")))

    conn1 = sqlite3.connect(first)
    conn2 = sqlite3.connect(second)
    assert conn1.execute("SELECT username FROM users").fetchall() == [("u1",)]
    assert conn2.execute("SELECT username FROM users").fetchall() == [("u2",)]
    conn1.close()
    conn2.close()
