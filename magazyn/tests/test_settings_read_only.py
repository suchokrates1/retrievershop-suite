import os

import pytest
from contextlib import contextmanager

from sqlalchemy import create_engine, text

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

    import magazyn.db as db_module

    temp_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(db_module, "engine", temp_engine)
    monkeypatch.setattr(db_module, "_is_postgres", False)

    with temp_engine.connect() as conn:
        conn.execute(text(SCHEMA))
        conn.commit()

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

    # Symulacja bazy read-only: db_connect rzuca wyjatek przy probie zapisu
    @contextmanager
    def failing_db_connect():
        raise RuntimeError("attempt to write a readonly database")

    monkeypatch.setattr(db_module, "db_connect", failing_db_connect)

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
