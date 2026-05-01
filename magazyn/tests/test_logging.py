import importlib
import logging
from types import SimpleNamespace

import magazyn.label_agent as label_agent_module
import magazyn.services.print_agent_runtime as print_agent_runtime
from magazyn.config import settings


def test_reload_config_updates_logger_level(monkeypatch):
    new_settings = SimpleNamespace(**vars(settings))
    new_settings.LOG_LEVEL = "DEBUG"
    monkeypatch.setattr(label_agent_module, "load_config", lambda: new_settings)

    print_agent_runtime.agent.reload_config()
    assert print_agent_runtime.logger.level == logging.DEBUG

    # restore original configuration
    monkeypatch.setattr(
        label_agent_module,
        "load_config",
        importlib.import_module("magazyn.config").load_config,
    )
    print_agent_runtime.agent.reload_config()
