import importlib
import sqlite3

import magazyn.config as cfg


def _prepare_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(cfg.settings, "DB_PATH", str(db_path))

    pkg = importlib.import_module("magazyn")
    importlib.reload(pkg)

    db_mod = importlib.import_module("magazyn.db")
    db = importlib.reload(db_mod)
    db.configure_engine(cfg.settings.DB_PATH)
    return db, db_path


def test_apply_migrations_records_executions(tmp_path, monkeypatch):
    db, db_path = _prepare_db(tmp_path, monkeypatch)

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    first = migrations_dir / "001_create_demo.py"
    first.write_text(
        """
import sqlite3
from magazyn import DB_PATH


def migrate():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS demo_entries (id INTEGER PRIMARY KEY, note TEXT)"
        )
        conn.execute("INSERT INTO demo_entries (note) VALUES ('first')")
        conn.commit()
"""
    )

    second = migrations_dir / "002_append_demo.py"
    second.write_text(
        """
import sqlite3
from magazyn import DB_PATH


def migrate():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO demo_entries (note) VALUES ('second')")
        conn.commit()
"""
    )

    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations_dir)

    db.init_db()

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT filename FROM schema_migrations ORDER BY filename"
        )
        applied = [row[0] for row in cur.fetchall()]
        demo_entries = conn.execute(
            "SELECT note FROM demo_entries ORDER BY id"
        ).fetchall()

    assert applied == ["001_create_demo.py", "002_append_demo.py"]
    assert [row[0] for row in demo_entries] == ["first", "second"]


def test_apply_migrations_skip_already_applied(tmp_path, monkeypatch):
    db, db_path = _prepare_db(tmp_path, monkeypatch)

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    (migrations_dir / "001_single_run.py").write_text(
        """
import sqlite3
from magazyn import DB_PATH


def migrate():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS run_guard (id INTEGER PRIMARY KEY)"
        )
        cur = conn.execute("SELECT COUNT(*) FROM run_guard")
        if cur.fetchone()[0]:
            raise RuntimeError("migration executed twice")
        conn.execute("INSERT INTO run_guard DEFAULT VALUES")
        conn.commit()
"""
    )

    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations_dir)

    db.init_db()

    with sqlite3.connect(db_path) as conn:
        initial = conn.execute(
            "SELECT filename, applied_at FROM schema_migrations"
        ).fetchall()

    db.init_db()

    with sqlite3.connect(db_path) as conn:
        final = conn.execute(
            "SELECT filename, applied_at FROM schema_migrations"
        ).fetchall()

    assert final == initial
