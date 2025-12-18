import pytest
from magazyn.factory import create_app
from magazyn.db import reset_db
from magazyn.settings_store import settings_store
from collections import OrderedDict

@pytest.fixture
def app(tmp_path, monkeypatch):
    """Create and configure a new app instance for each test."""
    # Use an isolated temporary database per test to avoid leaking state
    db_path = tmp_path / "test.db"
    log_path = tmp_path / "test.log"
    lock_path = tmp_path / "agent.lock"

    # Settings should be strings, just like when loaded from a .env file
    test_settings = OrderedDict([
        ("DB_PATH", str(db_path)),
        ("LOG_FILE", str(log_path)),
        ("LOCK_FILE", str(lock_path)),
        ("API_TOKEN", "test-token"),
        ("PAGE_ACCESS_TOKEN", "test-token"),
        ("ALLEGRO_ACCESS_TOKEN", ""),
        ("ALLEGRO_REFRESH_TOKEN", ""),
        ("ALLEGRO_SELLER_NAME", "Retriever Shop"),
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
        ("STATUS_ID", "123"),
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

    # 1. Prevent reading from .env files by patching the loader
    from magazyn import settings_io

    def _fake_load_settings(*, include_hidden=False, example_path=settings_io.EXAMPLE_PATH, env_path=settings_io.ENV_PATH, logger=None, on_error=None):
        values = OrderedDict(test_settings)
        if not example_path.exists():
            if on_error:
                on_error(f"Settings template missing: {example_path}")
        
        if not include_hidden:
            for hidden in settings_io.HIDDEN_KEYS:
                values.pop(hidden, None)
        return values

    monkeypatch.setattr('magazyn.settings_io.load_settings', _fake_load_settings)
    # Skip creating a default user or starting background threads during app factory
    monkeypatch.setattr('magazyn.factory.create_default_user_if_needed', lambda *args, **kwargs: None)
    monkeypatch.setattr('magazyn.factory.start_print_agent', lambda *args, **kwargs: None)

    # 2. Reset the internal state of the global settings_store singleton for test isolation
    monkeypatch.setattr(settings_store, '_loaded', False)
    monkeypatch.setattr(settings_store, '_values', OrderedDict())
    monkeypatch.setattr(settings_store, '_namespace', None)

    # 3. Create the app. This will trigger the settings to be loaded via our patch.
    app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SERVER_NAME': 'localhost',
    })

    # 4. Ensure the test database schema is freshly created for each test
    with app.app_context():
        reset_db()
        yield app


@pytest.fixture
def allegro_tokens():
    """Helper fixture to set Allegro OAuth tokens for a test."""

    from magazyn.env_tokens import update_allegro_tokens, clear_allegro_tokens

    def _set(access_token="test-access", refresh_token="test-refresh", expires_in=3600, metadata=None):
        update_allegro_tokens(access_token, refresh_token, expires_in, metadata)
        return access_token, refresh_token

    try:
        yield _set
    finally:
        clear_allegro_tokens()

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def login(client, app):
    """Log in a test user."""
    with app.app_context():
        with client.session_transaction() as sess:
            sess["username"] = "tester"
    yield

@pytest.fixture
def app_mod(app):
    """Import magazyn.app module with the test app configured."""
    import magazyn.app as app_mod
    # Store the test app in the module for tests that need it
    app_mod.app = app
    return app_mod
