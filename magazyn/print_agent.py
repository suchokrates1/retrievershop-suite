from __future__ import annotations

from .config import settings as _settings
from .label_agent import LabelAgent as _LabelAgent
from .services.print_agent_config import AgentConfig as _AgentConfig

agent = _LabelAgent(_AgentConfig.from_settings(_settings), _settings)
logger = agent.logger

__all__ = ["agent", "logger"]
