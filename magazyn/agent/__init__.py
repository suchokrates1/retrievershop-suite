"""Helpers for managing the legacy label printing agent."""

# Leniwy import aby uniknac cyklicznych zaleznosci
def __getattr__(name):
    if name == "migrate_main":
        from .migrate import main as migrate_main
        return migrate_main
    elif name == "AllegroSyncService":
        from .allegro_sync import AllegroSyncService
        return AllegroSyncService
    elif name in {"AgentConfig", "LabelAgent", "agent", "start_agent_thread", "stop_agent_thread"}:
        from .. import print_agent
        return getattr(print_agent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "migrate_main",
    "AllegroSyncService",
    "AgentConfig",
    "LabelAgent",
    "agent",
    "start_agent_thread",
    "stop_agent_thread",
]
