"""Persistent settings service backed by the SQLite database."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from typing import Iterable, Mapping, Optional

from . import settings_io

LOGGER = logging.getLogger(__name__)


class SettingsPersistenceError(RuntimeError):
    """Raised when settings cannot be persisted to any backing store."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%d %H:%M:%f', 'now'))
)
"""


def _default_db_path() -> Path:
    return Path(os.path.join(os.path.dirname(__file__), "database.db"))


class SettingsStore:
    """Store application configuration in the SQLite database."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._values: "OrderedDict[str, str]" = OrderedDict()
        self._namespace: Optional[SimpleNamespace] = None
        self._db_path: Path = _default_db_path()
        self._loaded = False
        self._db_last_updated_at: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_db_path(self, source: Mapping[str, str]) -> Path:
        db_path = source.get("DB_PATH") or os.environ.get("DB_PATH")
        if not db_path:
            return _default_db_path()
        return Path(db_path)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return

            env_values = settings_io.load_settings(
                include_hidden=True,
                example_path=settings_io.EXAMPLE_PATH,
                env_path=settings_io.ENV_PATH,
            )
            db_path = self._resolve_db_path(env_values)
            db_result = self._load_from_db(db_path)
            if db_result is None:
                db_values = None
                db_updated_at = None
            else:
                db_values, db_updated_at = db_result

            values = OrderedDict(env_values)
            if db_values:
                values.update(db_values)

            self._db_path = db_path
            self._values = OrderedDict(
                (key, "" if value is None else str(value)) for key, value in values.items()
            )
            self._namespace = self._build_namespace(self._values)
            self._apply_environment(self._values, replace_all=True)
            self._loaded = True
            self._db_last_updated_at = db_updated_at

    def _connect(self, db_path: Optional[Path] = None) -> Optional[sqlite3.Connection]:
        path = db_path or self._db_path
        if not path:
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
        except sqlite3.Error as exc:
            LOGGER.warning("Failed to connect to settings database: %s", exc)
            return None
        return conn

    def _load_from_db(
        self, db_path: Path
    ) -> Optional[tuple["OrderedDict[str, str]", Optional[str]]]:
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(db_path)
        except sqlite3.Error as exc:
            LOGGER.warning("Failed to read settings from %s: %s", db_path, exc)
            return None
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT key, value, updated_at FROM app_settings ORDER BY key"
                )
            except sqlite3.OperationalError as exc:
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
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return OrderedDict(), None
            LOGGER.warning("Failed to query app_settings: %s", exc)
            return None
        finally:
            conn.close()

        data: "OrderedDict[str, str]" = OrderedDict()
        latest: Optional[str] = None
        for row in rows:
            data[row["key"]] = row["value"] if row["value"] is not None else ""
            if "updated_at" in row.keys():
                row_updated_at = row["updated_at"]
                if isinstance(row_updated_at, str):
                    if latest is None or row_updated_at > latest:
                        latest = row_updated_at
        return data, latest

    def _fetch_last_updated_at(self, db_path: Optional[Path] = None) -> Optional[str]:
        conn = self._connect(db_path)
        if conn is None:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(updated_at) FROM app_settings")
            row = cursor.fetchone()
            if not row:
                return None
            value = row[0]
            return value if isinstance(value, str) else None
        except sqlite3.OperationalError as exc:
            if "no such column" in str(exc).lower():
                return None
            LOGGER.debug("Failed to read app_settings.updated_at: %s", exc)
            return None
        finally:
            conn.close()

    def _persist_many(self, values: Mapping[str, str], db_path: Optional[Path] = None) -> bool:
        if not values:
            return True

        conn = self._connect(db_path)
        if conn is None:
            raise SettingsPersistenceError(
                "Failed to persist settings: the database is unavailable"
            )

        try:
            cursor = conn.cursor()
            cursor.execute(SCHEMA)
            rows = [
                (key, "" if value is None else str(value))
                for key, value in values.items()
            ]
            cursor.executemany(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES (?, ?, STRFTIME('%Y-%m-%d %H:%M:%f', 'now'))
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=STRFTIME('%Y-%m-%d %H:%M:%f', 'now')
                """,
                rows,
            )
            conn.commit()
            try:
                cursor.execute("SELECT MAX(updated_at) FROM app_settings")
                row = cursor.fetchone()
            except sqlite3.OperationalError as exc:
                if "no such column" in str(exc).lower():
                    row = None
                else:
                    raise
            if row:
                latest = row[0]
                if isinstance(latest, str):
                    self._db_last_updated_at = latest
            return True
        except sqlite3.Error as exc:
            LOGGER.exception("Failed to persist settings to database: %s", exc)
            raise SettingsPersistenceError(
                "Failed to persist settings to the database"
            ) from exc
        finally:
            conn.close()

    def _delete_keys(self, keys: Iterable[str], db_path: Optional[Path] = None) -> bool:
        keys = list(keys)
        if not keys:
            return True

        conn = self._connect(db_path)
        if conn is None:
            raise SettingsPersistenceError(
                "Failed to delete settings: the database is unavailable"
            )

        try:
            cursor = conn.cursor()
            cursor.execute(SCHEMA)
            cursor.executemany("DELETE FROM app_settings WHERE key=?", [(key,) for key in keys])
            conn.commit()
            try:
                cursor.execute("SELECT MAX(updated_at) FROM app_settings")
                row = cursor.fetchone()
            except sqlite3.OperationalError as exc:
                if "no such column" in str(exc).lower():
                    row = None
                else:
                    raise
            if row:
                latest = row[0]
                if isinstance(latest, str):
                    self._db_last_updated_at = latest
            return True
        except sqlite3.Error as exc:
            LOGGER.exception("Failed to delete settings from database: %s", exc)
            raise SettingsPersistenceError(
                "Failed to delete settings from the database"
            ) from exc
        finally:
            conn.close()

    def _build_namespace(self, values: Mapping[str, str]) -> SimpleNamespace:
        processed_values = {}
        defaults = settings_io.load_settings(include_hidden=True)
        # Settings not present in .env.example but still expected across the codebase
        defaults.setdefault("ALLEGRO_SELLER_NAME", "")
        defaults.setdefault("ALLEGRO_SCRAPER_API_URL", "")  # e.g. http://192.168.31.150:5555
        all_keys = set(values.keys()) | set(defaults.keys())

        for key in all_keys:
            value = values.get(key, defaults.get(key))
            if key.endswith('_AT') and value:
                try:
                    processed_values[key] = float(value)
                except (ValueError, TypeError):
                    processed_values[key] = value
            elif key.startswith('ENABLE_') or key.endswith('_ENABLED'):
                processed_values[key] = (value or "0") == "1"
            elif 'INTERVAL' in key or 'EXPIRY' in key or 'THRESHOLD' in key or 'PORT' in key or ('ID' in key and key not in ['RECIPIENT_ID', 'ALLEGRO_SELLER_ID']):
                try:
                    processed_values[key] = int(value)
                except (ValueError, TypeError):
                        processed_values[key] = value
            else:
                processed_values[key] = value

        return SimpleNamespace(**processed_values)

    def _apply_environment(
        self,
        values: Mapping[str, str],
        removed: Iterable[str] = (),
        *,
        replace_all: bool = False,
    ) -> None:
        for key in removed:
            os.environ.pop(key, None)

        target = values if not replace_all else self._values
        for key, value in target.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def settings(self) -> SimpleNamespace:
        self._ensure_loaded()
        self._refresh_if_stale()
        assert self._namespace is not None
        return self._namespace

    def as_ordered_dict(
        self,
        *,
        include_hidden: bool = False,
        logger=None,
        on_error=None,
    ) -> "OrderedDict[str, str]":
        self._ensure_loaded()
        self._refresh_if_stale()
        # _refresh_if_stale() may trigger reload() which resets the loaded flag.
        # Ensure the values are available before reading from the cached mapping.
        self._ensure_loaded()
        ordered = settings_io.load_settings(
            include_hidden=include_hidden,
            logger=logger,
            on_error=on_error,
            example_path=settings_io.EXAMPLE_PATH,
            env_path=settings_io.ENV_PATH,
        )
        result: "OrderedDict[str, str]" = OrderedDict()

        for key in ordered.keys():
            if not include_hidden and key in settings_io.HIDDEN_KEYS:
                continue
            result[key] = self._values.get(key, ordered[key])

        for key, value in self._values.items():
            if key not in result and (
                include_hidden or key not in settings_io.HIDDEN_KEYS
            ):
                result[key] = value

        return result

    def update(self, values: Mapping[str, str]) -> None:
        self._ensure_loaded()
        with self._lock:
            previous_values = OrderedDict(self._values)
            changed: OrderedDict[str, str] = OrderedDict()
            removed: list[str] = []
            for key, value in values.items():
                if value is None:
                    if key in self._values:
                        self._values.pop(key, None)
                        removed.append(key)
                    continue
                str_value = str(value)
                current = self._values.get(key)
                if current == str_value:
                    continue
                self._values[key] = str_value
                changed[key] = str_value

            if not changed and not removed:
                return

            try:
                if changed:
                    self._persist_many(changed)
                if removed:
                    self._delete_keys(removed)
            except SettingsPersistenceError:
                self._values = previous_values
                self._namespace = self._build_namespace(self._values)
                raise

            self._apply_environment(changed, removed)
            self._namespace = self._build_namespace(self._values)


    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Return a configuration value from the persistent store."""

        self._ensure_loaded()
        self._refresh_if_stale()
        return self._values.get(key, default)

    def _refresh_if_stale(self) -> None:
        if not self._loaded or not self._db_path:
            return
        latest = self._fetch_last_updated_at()
        if latest is None:
            return
        with self._lock:
            if not self._loaded:
                return
            current = self._db_last_updated_at
        if current is not None and latest <= current:
            return

        db_result = self._load_from_db(self._db_path)
        if db_result is not None:
            db_values, db_updated_at = db_result
            if db_values:
                with self._lock:
                    self._values.update(db_values)
                    self._namespace = self._build_namespace(self._values)
                    self._db_last_updated_at = db_updated_at

    def reload(self) -> None:
        """Force reload settings from environment and database."""
        with self._lock:
            self._loaded = False
        self._ensure_loaded()


settings_store = SettingsStore()

__all__ = ["settings_store", "SettingsStore", "SettingsPersistenceError"]
