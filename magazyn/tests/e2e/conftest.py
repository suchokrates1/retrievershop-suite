"""Konfiguracja testow E2E Playwright.

Uruchamia aplikacje Flask na losowym porcie i udostepnia
fixture `live_url` oraz `page` z Playwright.
"""
import io
import pathlib

import pytest
import threading
from collections import OrderedDict
from werkzeug.serving import make_server

from PIL import Image

# ---------------------------------------------------------------------------
# Katalog z referencyjnymi snapshotami (obok tego pliku)
# ---------------------------------------------------------------------------
SNAPSHOTS_DIR = pathlib.Path(__file__).parent / "snapshots"
MAX_SNAPSHOT_HEIGHT = 7800


# Rejestrujemy opcje w sposob kompatybilny z pytest-playwright
# (oba pluginy definiuja pytest_addoption, wiec musi to byc conftest plugin)
def pytest_addoption(parser):
    group = parser.getgroup("snapshots", "Visual snapshot comparison")
    group.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Nadpisuje referencyjne snapshoty nowymi zrzutami.",
    )


def _pixel_diff_ratio(img_a: Image.Image, img_b: Image.Image) -> float:
    """Zwraca ulamek pikseli rozniących sie miedzy dwoma obrazami RGBA.

    Jesli obrazy maja rozna wysokosc (np. przez dynamiczna tresc),
    porownuje wspolna czesc i dodaje kare za roznice wysokosci.
    """
    wa, ha = img_a.size
    wb, hb = img_b.size
    if wa != wb:
        return 1.0
    w = wa
    h_common = min(ha, hb)
    h_max = max(ha, hb)
    px_a = img_a.load()
    px_b = img_b.load()
    diff = 0
    for y in range(h_common):
        for x in range(w):
            if px_a[x, y] != px_b[x, y]:
                diff += 1
    # Piksele poza wspolna czescia traktujemy jako rozne
    diff += w * (h_max - h_common)
    return diff / (w * h_max)


def _normalize_snapshot_image(img: Image.Image) -> Image.Image:
    """Przycina zrzut do bezpiecznej wysokosci, aby unikac limitow narzedzi."""
    if img.height <= MAX_SNAPSHOT_HEIGHT:
        return img
    return img.crop((0, 0, img.width, MAX_SNAPSHOT_HEIGHT))


def _normalize_snapshot_bytes(screenshot_bytes: bytes) -> bytes:
    """Normalizuje screenshot bytes do deterministycznego formatu PNG."""
    img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGBA")
    img = _normalize_snapshot_image(img)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def assert_snapshot(request):
    """Fixture do porownywania snapshotow.

    Uzycie w tescie::

        def test_foo(assert_snapshot, logged_in_page):
            assert_snapshot(logged_in_page.screenshot(full_page=True), "foo.png")
    """
    update = request.config.getoption("--update-snapshots")

    def _compare(screenshot_bytes: bytes, name: str, max_diff_ratio: float = 0.05):
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ref_path = SNAPSHOTS_DIR / name
        normalized_bytes = _normalize_snapshot_bytes(screenshot_bytes)

        if update or not ref_path.exists():
            ref_path.write_bytes(normalized_bytes)
            return

        ref_img = _normalize_snapshot_image(Image.open(ref_path).convert("RGBA"))
        new_img = Image.open(io.BytesIO(normalized_bytes)).convert("RGBA")
        ratio = _pixel_diff_ratio(ref_img, new_img)
        if ratio > max_diff_ratio:
            # Zapisz aktualny screenshot do analizy
            actual_path = ref_path.with_suffix(".actual.png")
            actual_path.write_bytes(normalized_bytes)
            pytest.fail(
                f"Snapshot '{name}' rozni sie o {ratio:.2%} (limit {max_diff_ratio:.0%}). "
                f"Aktualny zrzut: {actual_path}"
            )

    return _compare


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
        ("API_TOKEN", "test-token"),
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

    _orig_load = settings_io.load_settings

    def _fake_load(*, include_hidden=False, **kwargs):
        values = OrderedDict(test_settings)
        if not include_hidden:
            for hidden in settings_io.HIDDEN_KEYS:
                values.pop(hidden, None)
        return values

    settings_io.load_settings = _fake_load

    import magazyn.factory as factory
    _orig_create_user = factory.create_default_user_if_needed
    _orig_start_agent = factory.start_print_agent
    factory.create_default_user_if_needed = lambda *a, **kw: None
    factory.start_print_agent = lambda *a, **kw: None

    settings_store._loaded = False
    settings_store._values = OrderedDict()
    settings_store._namespace = None

    app = factory.create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "LOGIN_DISABLED": True,
    })

    from magazyn.db import reset_db
    with app.app_context():
        reset_db()
        # Tworzymy uzytkownika testowego
        from magazyn.db import get_session
        from magazyn.models import User
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
def logged_in_page(page, live_url):
    """Strona z zalogowanym uzytkownikiem."""
    page.goto(f"{live_url}/login")
    page.fill("input[name='username']", "testuser")
    page.fill("input[name='password']", "testpass123")
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")
    return page
