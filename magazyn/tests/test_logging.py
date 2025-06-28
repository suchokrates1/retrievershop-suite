import importlib
import logging
from types import SimpleNamespace

import magazyn.print_agent as pa


def test_reload_config_updates_logger_level(monkeypatch):
    new_settings = SimpleNamespace(**vars(pa.settings))
    new_settings.LOG_LEVEL = "DEBUG"
    monkeypatch.setattr(pa, "load_config", lambda: new_settings)

    pa.reload_config()
    assert pa.logger.level == logging.DEBUG

    # restore original configuration
    monkeypatch.setattr(pa, "load_config", importlib.import_module("magazyn.config").load_config)
    pa.reload_config()
