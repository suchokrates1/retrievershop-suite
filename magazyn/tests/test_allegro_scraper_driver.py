from __future__ import annotations

import types

from magazyn import allegro_scraper


def test_log_step_records_logger(caplog) -> None:
    caplog.set_level("DEBUG", logger="magazyn.allegro_scraper")
    buffer: list[str] = []

    allegro_scraper._log_step(buffer, "Testowy krok")

    assert buffer == ["Testowy krok"]
    assert any("Testowy krok" in record.message for record in caplog.records)


def test_find_chromedriver_prefers_env(monkeypatch) -> None:
    path = "/opt/selenium/custom-chromedriver"
    monkeypatch.setenv("CHROMEDRIVER_PATH", path)

    assert allegro_scraper._find_chromedriver() == path


def test_find_chromedriver_uses_shutil_which(monkeypatch) -> None:
    monkeypatch.delenv("CHROMEDRIVER_PATH", raising=False)

    fake_shutil = types.SimpleNamespace(which=lambda name: "/usr/local/bin/chromedriver")
    monkeypatch.setattr(allegro_scraper, "shutil", fake_shutil)

    assert allegro_scraper._find_chromedriver() == "/usr/local/bin/chromedriver"


def test_find_chromedriver_checks_common_paths(monkeypatch) -> None:
    monkeypatch.delenv("CHROMEDRIVER_PATH", raising=False)

    fake_shutil = types.SimpleNamespace(which=lambda name: None)
    monkeypatch.setattr(allegro_scraper, "shutil", fake_shutil)

    def fake_exists(path: str) -> bool:
        return path == "/usr/lib/chromium/chromedriver"

    monkeypatch.setattr(allegro_scraper.os.path, "exists", fake_exists)

    assert allegro_scraper._find_chromedriver() == "/usr/lib/chromium/chromedriver"
