"""Warstwa odczytu i zapisu ustawien aplikacji w bazie danych."""

from __future__ import annotations

import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional

from sqlalchemy import text


APP_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class SettingsDatabaseGateway:
    def __init__(self, *, logger, engine_factory) -> None:
        self._logger = logger
        self._engine_factory = engine_factory

    def get_runtime_engine(self):
        """Zwroc skonfigurowany engine lub tymczasowy engine z DATABASE_URL."""
        from ..db import engine as configured_engine

        if configured_engine is not None:
            return configured_engine, False

        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url.startswith("postgresql"):
            return None, False

        try:
            return self._engine_factory(database_url, future=True, pool_pre_ping=True), True
        except Exception as exc:
            self._logger.warning("Failed to create temporary settings engine: %s", exc)
            return None, False

    def engine_matches_db_path(self, eng, db_path: Optional[Path]) -> bool:
        """Sprawdz, czy SQLite engine wskazuje te sama baze co zrodlo ustawien."""
        if db_path is None:
            return True

        url = getattr(eng, "url", None)
        if url is None or not str(url.drivername).startswith("sqlite"):
            return True

        engine_db = getattr(url, "database", None)
        if not engine_db or engine_db == ":memory:":
            return True

        try:
            return Path(engine_db).resolve() == Path(db_path).resolve()
        except OSError:
            return Path(engine_db) == Path(db_path)

    def load_via_engine(self, eng):
        """Laduje ustawienia z bazy przez SQLAlchemy engine."""
        try:
            with eng.connect() as conn:
                try:
                    rows = conn.execute(
                        text("SELECT key, value, updated_at FROM app_settings ORDER BY key")
                    ).fetchall()
                    has_updated_at = True
                except Exception as exc:
                    conn.rollback()
                    err = str(exc).lower()
                    if "no such table" in err or "does not exist" in err:
                        return OrderedDict(), None
                    if "no such column" in err:
                        try:
                            rows = conn.execute(
                                text("SELECT key, value FROM app_settings ORDER BY key")
                            ).fetchall()
                            has_updated_at = False
                        except Exception:
                            conn.rollback()
                            return OrderedDict(), None
                    else:
                        self._logger.warning("Failed to query app_settings: %s", exc)
                        return None

                data: "OrderedDict[str, str]" = OrderedDict()
                latest: Optional[str] = None
                for row in rows:
                    data[row[0]] = row[1] if row[1] is not None else ""
                    if has_updated_at:
                        latest = _latest_value(latest, row[2])
                return data, latest
        except Exception as exc:
            self._logger.warning("Failed to read settings from engine: %s", exc)
            return None

    def load_from_db(self, db_path: Path) -> Optional[tuple["OrderedDict[str, str]", Optional[str]]]:
        runtime_engine, should_dispose = self.get_runtime_engine()
        if runtime_engine is not None and self.engine_matches_db_path(runtime_engine, db_path):
            try:
                return self.load_via_engine(runtime_engine)
            finally:
                if should_dispose:
                    runtime_engine.dispose()

        if not db_path.exists():
            return None
        try:
            import sqlite3 as _sqlite3

            conn = _sqlite3.connect(str(db_path))
        except Exception as exc:
            self._logger.warning("Failed to read settings from %s: %s", db_path, exc)
            return None
        try:
            conn.row_factory = _sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT key, value, updated_at FROM app_settings ORDER BY key")
            except Exception as exc:
                if "no such column" in str(exc).lower():
                    cursor.execute("SELECT key, value FROM app_settings ORDER BY key")
                    rows = cursor.fetchall()
                    data = OrderedDict(
                        (row["key"], row["value"] if row["value"] is not None else "")
                        for row in rows
                    )
                    return data, None
                raise
            rows = cursor.fetchall()
        except Exception as exc:
            if "no such table" in str(exc).lower():
                return OrderedDict(), None
            self._logger.warning("Failed to query app_settings: %s", exc)
            return None
        finally:
            conn.close()

        data: "OrderedDict[str, str]" = OrderedDict()
        latest: Optional[str] = None
        for row in rows:
            data[row["key"]] = row["value"] if row["value"] is not None else ""
            if "updated_at" in row.keys():
                latest = _latest_value(latest, row["updated_at"])
        return data, latest

    def fetch_last_updated_at(self, db_path: Optional[Path]) -> Optional[str]:
        runtime_engine, should_dispose = self.get_runtime_engine()
        if runtime_engine is None:
            return None
        if not self.engine_matches_db_path(runtime_engine, db_path):
            if should_dispose:
                runtime_engine.dispose()
            return None
        try:
            with runtime_engine.connect() as conn:
                row = conn.execute(text("SELECT MAX(updated_at) FROM app_settings")).fetchone()
                if not row:
                    return None
                value = row[0]
                if value is None:
                    return None
                return value if isinstance(value, str) else str(value)
        except Exception as exc:
            err = str(exc).lower()
            if "no such column" in err or "does not exist" in err or "no such table" in err:
                return None
            self._logger.debug("Failed to read app_settings.updated_at: %s", exc)
            return None
        finally:
            if should_dispose:
                runtime_engine.dispose()

    def persist_many(self, values: Mapping[str, str]) -> Optional[str]:
        if not values:
            return None
        rows = [
            {"key": key, "value": "" if value is None else str(value), "now": _utc_now()}
            for key, value in values.items()
        ]
        return self._execute_mutation(
            rows,
            text("""
                INSERT INTO app_settings(key, value, updated_at)
                VALUES (:key, :value, :now)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """),
            "Failed to persist settings to database: %s",
        )

    def delete_keys(self, keys: Iterable[str]) -> Optional[str]:
        rows = [{"key": key} for key in keys]
        if not rows:
            return None
        return self._execute_mutation(
            rows,
            text("DELETE FROM app_settings WHERE key = :key"),
            "Failed to delete settings from database: %s",
        )

    def _execute_mutation(self, rows, statement, log_message: str) -> Optional[str]:
        from ..db import db_connect as _db_connect
        from ..db import engine as configured_engine
        from ..settings_store import SettingsPersistenceError

        runtime_engine, should_dispose = self.get_runtime_engine()
        if configured_engine is None and runtime_engine is not None:
            try:
                return _mutate_with_engine(runtime_engine, rows, statement)
            except Exception as exc:
                self._logger.exception(log_message, exc)
                raise SettingsPersistenceError(log_message % "") from exc
            finally:
                if should_dispose:
                    runtime_engine.dispose()

        try:
            with _db_connect() as conn:
                return _mutate_connection(conn, rows, statement)
        except SettingsPersistenceError:
            raise
        except Exception as exc:
            self._logger.exception(log_message, exc)
            raise SettingsPersistenceError(log_message % "") from exc


def _mutate_with_engine(engine, rows, statement) -> Optional[str]:
    with engine.connect() as conn:
        return _mutate_connection(conn, rows, statement)


def _mutate_connection(conn, rows, statement) -> Optional[str]:
    conn.execute(text(APP_SETTINGS_SCHEMA))
    conn.execute(statement, rows)
    conn.commit()
    try:
        row = conn.execute(text("SELECT MAX(updated_at) FROM app_settings")).fetchone()
    except Exception:
        conn.rollback()
        return None
    if not row:
        return None
    latest = row[0]
    if latest is None:
        return None
    return latest if isinstance(latest, str) else str(latest)


def _latest_value(current: Optional[str], value) -> Optional[str]:
    if value is None:
        return current
    value_str = value if isinstance(value, str) else str(value)
    if current is None or value_str > current:
        return value_str
    return current


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


__all__ = ["APP_SETTINGS_SCHEMA", "SettingsDatabaseGateway"]