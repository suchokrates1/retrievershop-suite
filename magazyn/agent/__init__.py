"""Helpers for managing the legacy label printing agent."""

# Leniwy import aby uniknac cyklicznych zaleznosci
def __getattr__(name):
    if name == "migrate_main":
        from .migrate import main as migrate_main
        return migrate_main
    elif name == "AllegroSyncService":
        from .allegro_sync import AllegroSyncService
        return AllegroSyncService
    elif name == "TrackingService":
        from .tracking import TrackingService
        return TrackingService
    elif name == "check_tracking_statuses":
        from .tracking import check_tracking_statuses
        return check_tracking_statuses
    elif name == "TRACKING_STATUS_MAP":
        from .tracking import TRACKING_STATUS_MAP
        return TRACKING_STATUS_MAP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "migrate_main",
    "AllegroSyncService",
    "TrackingService",
    "check_tracking_statuses",
    "TRACKING_STATUS_MAP",
]
