import logging
import sqlite3

import magazyn.db as db
from magazyn.db import sqlite_connect


def test_configure_engine_enables_wal_mode(tmp_path, monkeypatch):
    original_engine = db.engine
    original_session_local = db.SessionLocal
    test_db = tmp_path / "wal.db"

    try:
        # Note: apply_migrations() was removed in favor of Alembic
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


def test_configure_sqlite_connection_readonly(tmp_path, caplog):
    db_file = tmp_path / "readonly.db"

    # create the database so SQLite can open it in read-only mode later
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY)")

    readonly_uri = f"file:{db_file}?mode=ro"
    caplog.set_level(logging.WARNING, logger="magazyn.db")

    with sqlite3.connect(
        readonly_uri,
        uri=True,
        check_same_thread=False,
    ) as readonly_conn:
        db._configure_sqlite_connection(readonly_conn)

        busy_timeout = readonly_conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = readonly_conn.execute("PRAGMA foreign_keys").fetchone()[0]

    warning_messages = [record.getMessage() for record in caplog.records]

    assert any("journal_mode" in message for message in warning_messages)
    assert busy_timeout == db.SQLITE_BUSY_TIMEOUT_MS
    assert foreign_keys == 1
