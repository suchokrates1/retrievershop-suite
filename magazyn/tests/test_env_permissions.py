import os
import stat

import pytest


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only permission semantics")
def test_write_env_sets_strict_permissions(app_mod, tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text("FOO=bar\n", encoding="utf-8")

    monkeypatch.setattr(app_mod, "ENV_PATH", env_path)
    monkeypatch.setattr(app_mod, "EXAMPLE_PATH", example_path)

    with app_mod.app.app_context():
        app_mod.write_env({"FOO": "baz"})

    assert env_path.exists(), ".env should be created by write_env"
    mode = stat.S_IMODE(env_path.stat().st_mode)
    assert mode == 0o600
