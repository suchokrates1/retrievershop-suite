import os
import stat

import pytest

from magazyn import settings_io


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only permission semantics")
def test_write_env_sets_strict_permissions(app_mod, tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text("FOO=bar\n", encoding="utf-8")

    monkeypatch.setattr(settings_io, "ENV_PATH", env_path)
    monkeypatch.setattr(settings_io, "EXAMPLE_PATH", example_path)

    with app_mod.app.app_context():
        settings_io.write_env({"FOO": "baz"}, example_path=example_path, env_path=env_path)

    assert env_path.exists(), ".env should be created by write_env"
    mode = stat.S_IMODE(env_path.stat().st_mode)
    assert mode == 0o600
