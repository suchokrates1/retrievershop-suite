"""Helpers for managing the legacy label printing agent."""

# Leniwy import aby uniknac cyklicznych zaleznosci
def __getattr__(name):
    if name == "migrate_main":
        from .migrate import main as migrate_main
        return migrate_main
    elif name == "AllegroSyncService":
        from .allegro_sync import AllegroSyncService
        return AllegroSyncService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "migrate_main",
    "AllegroSyncService",
]
