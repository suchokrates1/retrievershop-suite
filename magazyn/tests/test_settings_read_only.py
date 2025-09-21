import os
import sqlite3

import pytest

from magazyn import settings_io
from magazyn.env_tokens import clear_allegro_tokens, update_allegro_tokens
from magazyn.settings_store import (
    SCHEMA,
    SettingsPersistenceError,
    settings_store,
)


@pytest.fixture
def read_only_settings_store(tmp_path):
    monkeypatch = pytest.MonkeyPatch()
    example_path = tmp_path / ".env.example"
    example_path.write_text(
        settings_io.EXAMPLE_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    db_path = tmp_path / "settings.db"

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)

    original_connect = sqlite3.connect

    def read_only_connect(target, *args, **kwargs):
        if str(target) == str(db_path):
            ro_kwargs = dict(kwargs)
            ro_kwargs.setdefault("uri", True)
            return original_connect(
                f"file:{db_path}?mode=ro", *args, **ro_kwargs
            )
        return original_connect(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", read_only_connect)
    monkeypatch.setattr("magazyn.settings_store.sqlite3.connect", read_only_connect)

    env_path.write_text(
        "\n".join(
            [
                "ALLEGRO_ACCESS_TOKEN=stored-access",
                "ALLEGRO_REFRESH_TOKEN=stored-refresh",
                f"DB_PATH={db_path}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings_io, "ENV_PATH", env_path)
    monkeypatch.setattr(settings_io, "EXAMPLE_PATH", example_path)
    monkeypatch.setenv("DB_PATH", str(db_path))

    settings_store.reload()

    try:
        yield env_path
    finally:
        monkeypatch.undo()
        settings_store.reload()


def test_update_tokens_read_only_database_preserves_tokens(read_only_settings_store):
    env_path = read_only_settings_store
    original_env = env_path.read_text(encoding="utf-8")
    original_access = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    original_refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")

    with pytest.raises(SettingsPersistenceError):
        update_allegro_tokens("new-access", "new-refresh")

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") == original_access
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") == original_refresh
    assert os.environ.get("ALLEGRO_ACCESS_TOKEN") == original_access
    assert os.environ.get("ALLEGRO_REFRESH_TOKEN") == original_refresh
    assert env_path.read_text(encoding="utf-8") == original_env


def test_clear_tokens_read_only_database_preserves_tokens(read_only_settings_store):
    env_path = read_only_settings_store
    original_env = env_path.read_text(encoding="utf-8")
    original_access = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    original_refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")

    with pytest.raises(SettingsPersistenceError):
        clear_allegro_tokens()

    assert settings_store.get("ALLEGRO_ACCESS_TOKEN") == original_access
    assert settings_store.get("ALLEGRO_REFRESH_TOKEN") == original_refresh
    assert os.environ.get("ALLEGRO_ACCESS_TOKEN") == original_access
    assert os.environ.get("ALLEGRO_REFRESH_TOKEN") == original_refresh
    assert env_path.read_text(encoding="utf-8") == original_env
