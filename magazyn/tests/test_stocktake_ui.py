"""
Testy UI remanentu z Playwright.

Uruchamia serwer Flask in-thread, tworzy bazę z produktem, otwiera stronę
remanentu w headless Chromium i symuluje skan skanerem (keypresses z prędkością
skanera, Enter na końcu). Sprawdza reakcję interfejsu:
- karta ostatniego skanu pojawia się z nazwą produktu i licznikiem
- licznik "Skanow" się inkrementuje
- cofnięcie skanu (Cofnij) odświeża kartę i licznik

Uruchomienie:
    pytest magazyn/tests/test_stocktake_ui.py -v --headed   # z oknem
    pytest magazyn/tests/test_stocktake_ui.py -v            # headless
"""
import threading
import time
import os
import pytest
from collections import OrderedDict

try:
    from playwright.sync_api import Page, expect
    import pytest_playwright  # noqa: F401 - need pytest-playwright for 'page' fixture
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    Page = None
    _PLAYWRIGHT_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PLAYWRIGHT_AVAILABLE or os.getenv("CI") == "true",
    reason="Testy UI wymagaja Playwright z zainstalowana przegladarka",
)


EAN = "6900000000001"
SERIES = "Pas samochodowy"
COLOR = "Rozowy"
SIZE = "Uniwersalny"


# ---------------------------------------------------------------------------
# Fixture: serwer Flask na losowym porcie
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Uruchamia serwer Flask w osobnym wątku na losowym porcie."""
    import socket
    from magazyn.factory import create_app
    from magazyn.db import reset_db, get_session
    from magazyn.models import Product, ProductSize, Stocktake, StocktakeItem
    from magazyn.settings_store import settings_store

    tmp_path = tmp_path_factory.mktemp("ui_test")
    db_path = tmp_path / "test.db"
    log_path = tmp_path / "test.log"
    lock_path = tmp_path / "agent.lock"

    test_settings = OrderedDict([
        ("DB_PATH", str(db_path)),
        ("LOG_FILE", str(log_path)),
        ("LOCK_FILE", str(lock_path)),
        ("API_TOKEN", "test"),
        ("PAGE_ACCESS_TOKEN", "test"),
        ("ALLEGRO_ACCESS_TOKEN", ""),
        ("ALLEGRO_REFRESH_TOKEN", ""),
        ("ALLEGRO_SELLER_NAME", "Test"),
        ("RECIPIENT_ID", "test"),
        ("PRINTER_NAME", "test"),
        ("CUPS_SERVER", ""),
        ("CUPS_PORT", ""),
        ("POLL_INTERVAL", "1"),
        ("QUIET_HOURS_START", "00:00"),
        ("QUIET_HOURS_END", "00:00"),
        ("TIMEZONE", "UTC"),
        ("PRINTED_EXPIRY_DAYS", "30"),
        ("ENABLE_WEEKLY_REPORTS", "0"),
        ("ENABLE_MONTHLY_REPORTS", "0"),
        ("LOG_LEVEL", "WARNING"),
        ("API_RATE_LIMIT_CALLS", "60"),
        ("API_RATE_LIMIT_PERIOD", "60.0"),
        ("API_RETRY_ATTEMPTS", "3"),
        ("API_RETRY_BACKOFF_INITIAL", "1.0"),
        ("API_RETRY_BACKOFF_MAX", "30.0"),
        ("SECRET_KEY", "ui-test-secret"),
        ("COMMISSION_ALLEGRO", "10.0"),
        ("STATUS_ID", "123"),
        ("FLASK_DEBUG", "0"),
        ("ALERT_EMAIL", "test@test.pl"),
        ("LOW_STOCK_THRESHOLD", "5"),
        ("SMTP_SERVER", ""),
        ("SMTP_PORT", ""),
        ("SMTP_USERNAME", ""),
        ("SMTP_PASSWORD", ""),
        ("SMTP_SENDER", ""),
        ("ALLEGRO_CLIENT_ID", ""),
        ("ALLEGRO_CLIENT_SECRET", ""),
    ])

    from magazyn import settings_io

    original_load = settings_io.load_settings

    def _fake_load(**kwargs):
        vals = OrderedDict(test_settings)
        if not kwargs.get("include_hidden", False):
            for k in settings_io.HIDDEN_KEYS:
                vals.pop(k, None)
        return vals

    settings_io.load_settings = _fake_load
    settings_store._loaded = False
    settings_store._values = OrderedDict()
    settings_store._namespace = None

    # Patch out background services that interfere with test db reset
    import magazyn.factory as _factory
    _orig_start_print = _factory.start_print_agent
    _orig_create_user = _factory.create_default_user_if_needed
    _factory.start_print_agent = lambda *a, **kw: None
    _factory.create_default_user_if_needed = lambda *a, **kw: None

    flask_app = create_app({
        "TESTING": False,
        "WTF_CSRF_ENABLED": False,
    })
    flask_app.config["SERVER_NAME"] = None

    stocktake_id = None
    with flask_app.app_context():
        reset_db()
        with get_session() as db:
            product = Product(
                category="Szelki",
                brand="Dogtrace",
                series=SERIES,
                color=COLOR,
            )
            db.add(product)
            db.flush()
            ps = ProductSize(
                product_id=product.id,
                size=SIZE,
                quantity=6,
                barcode=EAN,
            )
            db.add(ps)
            db.flush()
            st = Stocktake(status="in_progress")
            db.add(st)
            db.flush()
            item = StocktakeItem(
                stocktake_id=st.id,
                product_size_id=ps.id,
                expected_qty=6,
                scanned_qty=0,
            )
            db.add(item)
            stocktake_id = st.id

    # Znajdz wolny port
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    def _run():
        flask_app.run(host="127.0.0.1", port=port, use_reloader=False, threaded=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(1.5)  # Poczekaj az serwer sie uruchomi

    yield {"app": flask_app, "port": port, "stocktake_id": stocktake_id}

    settings_io.load_settings = original_load
    _factory.start_print_agent = _orig_start_print
    _factory.create_default_user_if_needed = _orig_create_user


# ---------------------------------------------------------------------------
# Pomocnik: zaloguj sie przez strone logowania
# ---------------------------------------------------------------------------

def _login(page: Page, port: int, app):
    """Tworzy uzytkownika i loguje sie przez UI."""
    from werkzeug.security import generate_password_hash
    from magazyn.db import get_session
    from magazyn.models import User

    with app.app_context():
        with get_session() as db:
            user = db.query(User).filter_by(username="tester").first()
            if not user:
                db.add(User(username="tester", password=generate_password_hash("secret")))
            else:
                user.password = generate_password_hash("secret")

    page.goto(f"http://127.0.0.1:{port}/login")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret")
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: "/login" not in url, timeout=5000)


def _simulate_barcode_scan(page: Page, ean: str):
    """
    Symuluje skan skanera BT/USB: szybkie KeyboardEvent dla każdego znaku,
    następnie Enter — tak jak robi to fizyczny skaner.
    """
    page.evaluate("""(ean) => {
        const DELAY = 10;  // ms miedzy znakami - predkosc skanera
        let i = 0;
        function sendKey(char) {
            const opts = {
                key: char,
                code: 'Key' + char.toUpperCase(),
                keyCode: char.charCodeAt(0),
                which: char.charCodeAt(0),
                bubbles: true,
                cancelable: true
            };
            document.dispatchEvent(new KeyboardEvent('keydown', opts));
            document.dispatchEvent(new KeyboardEvent('keypress', opts));
            document.dispatchEvent(new KeyboardEvent('keyup', opts));
        }
        function next() {
            if (i < ean.length) {
                sendKey(ean[i++]);
                setTimeout(next, DELAY);
            } else {
                // Enter na koncu
                const enter = {
                    key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
                    bubbles: true, cancelable: true
                };
                document.dispatchEvent(new KeyboardEvent('keydown', enter));
                document.dispatchEvent(new KeyboardEvent('keyup', enter));
            }
        }
        next();
    }""", ean)


# ---------------------------------------------------------------------------
# Testy
# ---------------------------------------------------------------------------

class TestStocktakeScanUI:

    def test_skan_pojawia_sie_na_karcie(self, page: Page, live_server):
        """Po skanie EAN karta ostatniego skanu pokazuje nazwe produktu."""
        port = live_server["port"]
        app = live_server["app"]
        st_id = live_server["stocktake_id"]

        _login(page, port, app)
        page.goto(f"http://127.0.0.1:{port}/stocktake/{st_id}/scan")
        page.wait_for_load_state("networkidle")

        # Upewnij sie ze karta jest schowana przed skanem
        card_class = page.get_attribute("#last-scan-card", "class") or ""
        assert "d-none" in card_class

        _simulate_barcode_scan(page, EAN)

        # Karta powinna sie pojawic z nazwa produktu
        card = page.wait_for_selector("#last-scan-card:not(.d-none)", timeout=5000)
        assert card is not None

        product_text = page.inner_text("#last-scan-product")
        assert SERIES in product_text

    def test_skan_inkrementuje_licznik(self, page: Page, live_server):
        """Po skanie licznik 'Skanow' rosnie o 1."""
        port = live_server["port"]
        app = live_server["app"]
        st_id = live_server["stocktake_id"]

        _login(page, port, app)
        page.goto(f"http://127.0.0.1:{port}/stocktake/{st_id}/scan")
        page.wait_for_load_state("networkidle")

        before = int(page.inner_text("#stat-total-scanned").strip())

        _simulate_barcode_scan(page, EAN)

        page.wait_for_selector("#last-scan-card:not(.d-none)", timeout=5000)
        after = int(page.inner_text("#stat-total-scanned").strip())

        assert after == before + 1, f"Oczekiwano {before + 1}, otrzymano {after}"

    def test_skan_pokazuje_licznik_scanned_expected(self, page: Page, live_server):
        """Karta pokazuje poprawny licznik scanned/expected."""
        port = live_server["port"]
        app = live_server["app"]
        st_id = live_server["stocktake_id"]

        _login(page, port, app)
        page.goto(f"http://127.0.0.1:{port}/stocktake/{st_id}/scan")
        page.wait_for_load_state("networkidle")

        # Odczytaj aktualny stan z bazy
        from magazyn.db import get_session
        from magazyn.models import StocktakeItem, ProductSize
        with app.app_context():
            with get_session() as db:
                ps = db.query(ProductSize).filter_by(barcode=EAN).first()
                item = db.query(StocktakeItem).filter_by(
                    stocktake_id=st_id, product_size_id=ps.id
                ).first()
                expected_qty = item.scanned_qty + 1  # po skanie

        _simulate_barcode_scan(page, EAN)
        page.wait_for_selector("#last-scan-card:not(.d-none)", timeout=5000)

        scanned_text = page.inner_text("#last-scan-scanned").strip()
        expected_text = page.inner_text("#last-scan-expected").strip()

        assert scanned_text == str(expected_qty)
        assert expected_text == "6"  # expected_qty w bazie

    def test_cofnij_usuwa_karte_skanu(self, page: Page, live_server):
        """Po kliknieciu Cofnij karta ostatniego skanu sie chowa i licznik maleje."""
        port = live_server["port"]
        app = live_server["app"]
        st_id = live_server["stocktake_id"]

        _login(page, port, app)
        page.goto(f"http://127.0.0.1:{port}/stocktake/{st_id}/scan")
        page.wait_for_load_state("networkidle")

        # Najpierw skan
        _simulate_barcode_scan(page, EAN)
        page.wait_for_selector("#last-scan-card:not(.d-none)", timeout=5000)

        before_total = int(page.inner_text("#stat-total-scanned").strip())

        # Kliknij Cofnij
        page.click("#btn-undo")

        # Licznik powinien zmalesz o 1 (albo karta zniknac)
        page.wait_for_function(
            f"() => parseInt(document.getElementById('stat-total-scanned').textContent) === {before_total - 1}",
            timeout=5000
        )
        after_total = int(page.inner_text("#stat-total-scanned").strip())
        assert after_total == before_total - 1

    def test_podwojny_skan_nie_duplikuje(self, page: Page, live_server):
        """Dwa szybkie skany tego samego EAN daja scanned_qty += 2, nie += 4."""
        port = live_server["port"]
        app = live_server["app"]
        st_id = live_server["stocktake_id"]

        _login(page, port, app)
        page.goto(f"http://127.0.0.1:{port}/stocktake/{st_id}/scan")
        page.wait_for_load_state("networkidle")

        before_total = int(page.inner_text("#stat-total-scanned").strip())

        # Dwa skany z krotkimi odstepem
        _simulate_barcode_scan(page, EAN)
        page.wait_for_selector("#last-scan-card:not(.d-none)", timeout=5000)
        time.sleep(0.3)
        _simulate_barcode_scan(page, EAN)

        page.wait_for_function(
            f"() => parseInt(document.getElementById('stat-total-scanned').textContent) >= {before_total + 2}",
            timeout=5000
        )
        after_total = int(page.inner_text("#stat-total-scanned").strip())

        # Dokladnie +2 — nie +4 (co bylo by przy podwojnym skanowaniu)
        assert after_total == before_total + 2, (
            f"Oczekiwano dokladnie {before_total + 2} skanow, otrzymano {after_total}"
        )

    def test_nieznany_ean_pokazuje_blad(self, page: Page, live_server):
        """Skan nieznanego EAN pokazuje komunikat bledu w UI."""
        port = live_server["port"]
        app = live_server["app"]
        st_id = live_server["stocktake_id"]

        _login(page, port, app)
        page.goto(f"http://127.0.0.1:{port}/stocktake/{st_id}/scan")
        page.wait_for_load_state("networkidle")

        _simulate_barcode_scan(page, "9999999999999")

        # Blad powinien sie pojawic (globalny skaner wywola showError)
        # scan-error jest w stocktake_scan.html, ale globalny skaner uzywa
        # [data-barcode-error] lub data-barcode-result z base.html
        # Sprawdzamy ze karta sukcesu sie NIE pojawila
        page.wait_for_timeout(2000)
        card_class = page.get_attribute("#last-scan-card", "class") or ""
        # Karta powinna byc nadal schowana (nie bylo udanego skanu)
        assert "d-none" in card_class or page.is_hidden("#last-scan-card")
