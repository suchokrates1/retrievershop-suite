from .settings_store import settings_store


def load_config():
    """Return the cached configuration namespace."""

    return settings_store.settings


class _SettingsProxy:
    """Dynamic proxy exposing the latest configuration values."""

    def __getattribute__(self, item):
        if item == "__dict__":
            return vars(settings_store.settings)
        return super().__getattribute__(item)

    def __getattr__(self, item):
        return getattr(settings_store.settings, item)

    def __setattr__(self, key, value):
        if key.startswith("_"):
            return super().__setattr__(key, value)
        settings_store.update({key: value})


settings = _SettingsProxy()
