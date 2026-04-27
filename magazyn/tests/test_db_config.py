from types import SimpleNamespace
from werkzeug.security import generate_password_hash

import magazyn.db as db
import magazyn.label_agent as label_agent_module
import magazyn.print_agent as pa
from magazyn.config import settings
from magazyn.models.users import User
from magazyn.db import sqlite_connect


def test_reload_env_reconfigures_engine(tmp_path, monkeypatch):
    first = tmp_path / "first.db"
    # Note: apply_migrations() was removed in favor of Alembic
    db.configure_engine(str(first))
    db.init_db()
    with db.get_session() as session:
        session.add(User(username="u1", password=generate_password_hash("p")))

    second = tmp_path / "second.db"
    new_settings = SimpleNamespace(**vars(settings))
    new_settings.DB_PATH = str(second)
    monkeypatch.setattr(label_agent_module, "load_config", lambda: new_settings)

    pa.agent.reload_config()

    db.init_db()
    with db.get_session() as session:
        session.add(User(username="u2", password=generate_password_hash("p")))

    conn1 = sqlite_connect(first)
    conn2 = sqlite_connect(second)
    assert conn1.execute("SELECT username FROM users").fetchall() == [("u1",)]
    assert conn2.execute("SELECT username FROM users").fetchall() == [("u2",)]
    conn1.close()
    conn2.close()
