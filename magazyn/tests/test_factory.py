from collections import OrderedDict

from magazyn.config import settings
from magazyn import db as db_mod
from magazyn import factory


def test_create_app_initializes_agent_and_migrations(tmp_path, monkeypatch):
    tmp_db_path = tmp_path / "app.db"

    from magazyn.settings_store import settings_store
    from magazyn import settings_io

    test_settings = OrderedDict([
        ("DB_PATH", str(tmp_db_path)),
        ("LOG_FILE", str(tmp_path / "test.log")),
        ("LOCK_FILE", str(tmp_path / "agent.lock")),
        ("PAGE_ACCESS_TOKEN", "test-token"),
        ("ALLEGRO_ACCESS_TOKEN", ""),
        ("ALLEGRO_REFRESH_TOKEN", ""),
        ("RECIPIENT_ID", "test-id"),
        ("PRINTER_NAME", "test-printer"),
        ("CUPS_SERVER", ""),
        ("CUPS_PORT", ""),
        ("POLL_INTERVAL", "1"),
        ("QUIET_HOURS_START", "00:00"),
        ("QUIET_HOURS_END", "00:00"),
        ("TIMEZONE", "UTC"),
        ("PRINTED_EXPIRY_DAYS", "30"),
        ("ENABLE_WEEKLY_REPORTS", "0"),
        ("ENABLE_MONTHLY_REPORTS", "0"),
        ("LOG_LEVEL", "DEBUG"),
        ("API_RATE_LIMIT_CALLS", "60"),
        ("API_RATE_LIMIT_PERIOD", "60.0"),
        ("API_RETRY_ATTEMPTS", "3"),
        ("API_RETRY_BACKOFF_INITIAL", "1.0"),
        ("API_RETRY_BACKOFF_MAX", "30.0"),
        ("SECRET_KEY", "test-secret-key"),
        ("COMMISSION_ALLEGRO", "10.0"),
        ("FLASK_DEBUG", "0"),
        ("ALERT_EMAIL", "test@example.com"),
        ("LOW_STOCK_THRESHOLD", "5"),
        ("SMTP_SERVER", ""),
        ("SMTP_PORT", ""),
        ("SMTP_USERNAME", ""),
        ("SMTP_PASSWORD", ""),
        ("SMTP_SENDER", ""),
        ("ALLEGRO_CLIENT_ID", ""),
        ("ALLEGRO_CLIENT_SECRET", ""),
    ])

    def _fake_load_settings(*, include_hidden=False, example_path=settings_io.EXAMPLE_PATH,
                            env_path=settings_io.ENV_PATH, logger=None, on_error=None):
        return OrderedDict(test_settings)

    monkeypatch.setattr('magazyn.settings_io.load_settings', _fake_load_settings)

    monkeypatch.setattr(settings_store, '_loaded', False)
    monkeypatch.setattr(settings_store, '_values', OrderedDict())
    monkeypatch.setattr(settings_store, '_namespace', None)

    call_order = []
    original_ensure = factory.ensure_db_initialized

    def tracking_ensure(app_obj=None):
        call_order.append(("ensure", app_obj))
        original_ensure(app_obj)

    monkeypatch.setattr(factory, "ensure_db_initialized", tracking_ensure)

    def fake_start_agent(app_obj=None):
        call_order.append(("start", app_obj))

    monkeypatch.setattr(factory, "start_print_agent", fake_start_agent)
    monkeypatch.setattr(factory, "create_default_user_if_needed", lambda app: None)

    app = factory.create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    assert ("ensure", app) in call_order, "Database init should be triggered immediately"
    assert ("start", app) in call_order, "Agent should start during app creation"
    assert call_order.index(("ensure", app)) < call_order.index(("start", app))
