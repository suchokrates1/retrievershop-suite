"""Konfiguracja testow E2E Playwright.

Uruchamia aplikacje Flask na losowym porcie i udostepnia
fixture `live_url` oraz `page` z Playwright.
"""
import threading

import pytest
from collections import OrderedDict
from flask.sessions import SecureCookieSessionInterface
from werkzeug.serving import make_server


@pytest.fixture(scope="session")
def _e2e_app(tmp_path_factory):
    """Tworzy instancje aplikacji dla testow E2E."""
    tmp = tmp_path_factory.mktemp("e2e")
    db_path = tmp / "e2e_test.db"

    from magazyn import settings_io
    from magazyn.settings_store import settings_store

    test_settings = OrderedDict([
        ("DB_PATH", str(db_path)),
        ("LOG_FILE", str(tmp / "e2e.log")),
        ("LOCK_FILE", str(tmp / "agent.lock")),
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
        ("SECRET_KEY", "e2e-secret-key"),
        ("COMMISSION_ALLEGRO", "10.0"),
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

    _orig_load = settings_io.load_settings

    def _fake_load(*, include_hidden=False, **kwargs):
        values = OrderedDict(test_settings)
        if not include_hidden:
            for hidden in settings_io.HIDDEN_KEYS:
                values.pop(hidden, None)
        return values

    settings_io.load_settings = _fake_load

    import magazyn.factory as factory
    import magazyn.app as app_module
    import magazyn.config as config_module
    _orig_create_user = factory.create_default_user_if_needed
    _orig_start_agent = factory.start_print_agent
    _orig_factory_settings = factory.settings
    _orig_app_settings = app_module.settings
    _orig_config_settings = config_module.settings
    factory.create_default_user_if_needed = lambda *a, **kw: None
    factory.start_print_agent = lambda *a, **kw: None

    settings_store._loaded = False
    settings_store._values = OrderedDict()
    settings_store._namespace = None
    refreshed_settings = settings_store.settings
    factory.settings = refreshed_settings
    app_module.settings = refreshed_settings
    config_module.settings = refreshed_settings

    app = factory.create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "LOGIN_DISABLED": True,
    })

    from magazyn.db import configure_engine, reset_db
    configure_engine(str(db_path))
    with app.app_context():
        reset_db()
        from magazyn.db import get_session
        from magazyn.models.users import User
        from werkzeug.security import generate_password_hash
        with get_session() as db:
            test_user = User(
                username="testuser",
                password=generate_password_hash("testpass123"),
            )
            db.add(test_user)
            db.commit()

    yield app

    settings_io.load_settings = _orig_load
    factory.create_default_user_if_needed = _orig_create_user
    factory.start_print_agent = _orig_start_agent
    factory.settings = _orig_factory_settings
    app_module.settings = _orig_app_settings
    config_module.settings = _orig_config_settings


@pytest.fixture(scope="session")
def live_url(_e2e_app):
    """Uruchamia serwer Flask w watku i zwraca URL bazowy."""
    server = make_server("127.0.0.1", 0, _e2e_app)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture(scope="session")
def browser_context_args():
    """Domyslne ustawienia przegladarki dla testow."""
    return {
        "locale": "pl-PL",
        "timezone_id": "Europe/Warsaw",
    }


@pytest.fixture
def logged_in_page(page, live_url, _e2e_app):
    """Strona z zalogowanym uzytkownikiem."""
    serializer = SecureCookieSessionInterface().get_signing_serializer(_e2e_app)
    session_cookie = serializer.dumps({"username": "testuser"})
    page.context.add_cookies([
        {
            "name": _e2e_app.config.get("SESSION_COOKIE_NAME", "session"),
            "value": session_cookie,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "sameSite": "Lax",
        }
    ])
    page.goto(f"{live_url}/")
    page.wait_for_load_state("networkidle")
    return page
