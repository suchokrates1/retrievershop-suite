import pytest
from magazyn.factory import create_app
from magazyn.settings_store import settings_store
from collections import OrderedDict

@pytest.fixture
def app(tmp_path, monkeypatch):
    """Create and configure a new app instance for each test."""
    # Use existing production database for tests
    db_path = r"d:\Serwer\obecność\templates\docx_templates\database.db"
    log_path = tmp_path / "test.log"
    lock_path = tmp_path / "agent.lock"

    # Settings should be strings, just like when loaded from a .env file
    test_settings = OrderedDict([
        ("DB_PATH", str(db_path)),
        ("LOG_FILE", str(log_path)),
        ("LOCK_FILE", str(lock_path)),
        ("API_TOKEN", "test-token"),
        ("PAGE_ACCESS_TOKEN", "test-token"),
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
    monkeypatch.setattr('magazyn.settings_io.load_settings', lambda *args, **kwargs: test_settings)

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

    # 4. Now we are in an app context with the correct DB engine.
    # Note: We use existing production database, so we don't call reset_db()
    with app.app_context():
        yield app

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
