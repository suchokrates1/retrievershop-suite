import magazyn.db as db
from magazyn.db import sqlite_connect


def test_configure_engine_enables_wal_mode(tmp_path, monkeypatch):
    original_engine = db.engine
    original_session_local = db.SessionLocal
    test_db = tmp_path / "wal.db"

    try:
        monkeypatch.setattr(db, "apply_migrations", lambda: None)
        db.configure_engine(str(test_db))
        db.init_db()

        with db.engine.connect() as conn:
            journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar_one()
        assert journal_mode.lower() == "wal"

        with sqlite_connect(test_db) as raw_conn:
            raw_mode = raw_conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert raw_mode.lower() == "wal"
    finally:
        if db.engine is not None and db.engine is not original_engine:
            db.engine.dispose()
        db.engine = original_engine
        db.SessionLocal = original_session_local
