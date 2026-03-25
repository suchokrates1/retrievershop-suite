"""Testy E2E przez przegladarke CDP (Chrome DevTools Protocol).

Wymagaja uruchomionego Chromium z CDP na minipc (lub innym hoscie).
Pomijane automatycznie jesli CDP jest niedostepny.

Uruchomienie:
    pytest magazyn/tests/test_e2e_browser.py -m e2e -v

Konfiguracja (zmienne srodowiskowe):
    E2E_CDP_HOST  - host CDP (domyslnie: 192.168.31.147)
    E2E_CDP_PORT  - port CDP (domyslnie: 9223)
    E2E_BASE_URL  - URL aplikacji (domyslnie: https://magazyn.retrievershop.pl)
    E2E_PASSWORD  - haslo do logowania (wymagane)
    E2E_USERNAME  - uzytkownik (domyslnie: admin)
"""

import asyncio
import json
import os
import time
import urllib.request

import pytest

CDP_HOST = os.environ.get("E2E_CDP_HOST", "192.168.31.147")
CDP_PORT = int(os.environ.get("E2E_CDP_PORT", "9223"))
BASE_URL = os.environ.get("E2E_BASE_URL", "https://magazyn.retrievershop.pl")
USERNAME = os.environ.get("E2E_USERNAME", "admin")
PASSWORD = os.environ.get("E2E_PASSWORD", "")

# ---- Sprawdzenie dostepu do CDP ----

def _cdp_available():
    try:
        url = f"http://{CDP_HOST}:{CDP_PORT}/json/version"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read())
            return "Browser" in data
    except Exception:
        return False


CDP_AVAILABLE = _cdp_available()
skip_no_cdp = pytest.mark.skipif(
    not CDP_AVAILABLE, reason=f"CDP niedostepny na {CDP_HOST}:{CDP_PORT}"
)
skip_no_password = pytest.mark.skipif(
    not PASSWORD, reason="Brak E2E_PASSWORD - ustaw zmienna srodowiskowa"
)

# ---- Narzedzia CDP ----

_msg_counter = 0


def _next_id():
    global _msg_counter
    _msg_counter += 1
    return _msg_counter


async def _cdp_call(ws, method, params=None, timeout=15):
    mid = _next_id()
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
        except asyncio.TimeoutError:
            continue
        data = json.loads(raw)
        if data.get("id") == mid:
            if "error" in data:
                raise RuntimeError(f"CDP error: {data['error']}")
            return data.get("result", {})
    raise TimeoutError(f"CDP timeout: {method}")


async def _collect_events(ws, duration=1.5):
    events = []
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.3)
            data = json.loads(raw)
            if "method" in data:
                events.append(data)
        except asyncio.TimeoutError:
            pass
    return events


async def _navigate(ws, url, timeout=20):
    await _cdp_call(ws, "Page.enable")
    t0 = time.monotonic()
    await _cdp_call(ws, "Page.navigate", {"url": url})
    deadline = t0 + timeout
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            if data.get("method") == "Page.loadEventFired":
                return int((time.monotonic() - t0) * 1000)
        except asyncio.TimeoutError:
            continue
    return int((time.monotonic() - t0) * 1000)


async def _js(ws, expression):
    result = await _cdp_call(ws, "Runtime.evaluate", {"expression": expression})
    return result.get("result", {}).get("value")


def _extract_console_errors(events):
    """Wyciaga bledy z eventow CDP konsoli."""
    errors = []
    for ev in events:
        method = ev.get("method", "")
        params = ev.get("params", {})

        if method == "Console.messageAdded":
            msg = params.get("message", {})
            if msg.get("level") == "error":
                text = msg.get("text", "")
                # Ignoruj 404 favicon - nie jest bledem JS
                if "favicon" not in text.lower():
                    errors.append(text)

        elif method == "Runtime.consoleAPICalled":
            if params.get("type") == "error":
                args = params.get("args", [])
                text = " ".join(
                    a.get("value", a.get("description", "")) for a in args
                )
                if "favicon" not in text.lower():
                    errors.append(text)

        elif method == "Runtime.exceptionThrown":
            exc = params.get("exceptionDetails", {})
            text = exc.get("text", "")
            exc_obj = exc.get("exception", {})
            desc = exc_obj.get("description", exc_obj.get("value", ""))
            full = f"{text}: {desc}" if desc else text
            errors.append(full)

        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            if entry.get("level") == "error":
                text = entry.get("text", "")
                if "favicon" not in text.lower():
                    errors.append(text)

    return errors


# ---- Fixture CDP ----


class CDPSession:
    """Sesja CDP z przegladarka - tworzy karte, loguje sie, udostepnia metody."""

    def __init__(self):
        self.ws = None
        self.page_id = None
        self.logged_in = False

    async def connect(self):
        import websockets

        # Nowa karta
        url = f"http://{CDP_HOST}:{CDP_PORT}/json/new"
        req = urllib.request.Request(url, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as resp:
            page = json.loads(resp.read())
        self.page_id = page["id"]
        ws_url = page["webSocketDebuggerUrl"]
        ws_url = ws_url.replace("localhost", CDP_HOST).replace("127.0.0.1", CDP_HOST)
        self.ws = await websockets.connect(ws_url, max_size=10 * 1024 * 1024)
        await _cdp_call(self.ws, "Console.enable")
        await _cdp_call(self.ws, "Runtime.enable")
        await _cdp_call(self.ws, "Log.enable")

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.page_id:
            close_url = f"http://{CDP_HOST}:{CDP_PORT}/json/close/{self.page_id}"
            try:
                with urllib.request.urlopen(close_url, timeout=5):
                    pass
            except Exception:
                pass

    async def login(self):
        await _navigate(self.ws, f"{BASE_URL}/login")
        await asyncio.sleep(1)

        current = await _js(self.ws, "window.location.href")
        if "/login" not in current:
            self.logged_in = True
            return

        await _js(self.ws, f"""
        (function() {{
            document.querySelector('input[name="username"]').value = {json.dumps(USERNAME)};
            document.querySelector('input[name="password"]').value = {json.dumps(PASSWORD)};
            document.querySelector('input[name="username"]').dispatchEvent(new Event('input', {{bubbles:true}}));
            document.querySelector('input[name="password"]').dispatchEvent(new Event('input', {{bubbles:true}}));
            document.querySelector('form').submit();
        }})()
        """)
        await asyncio.sleep(3)
        await _collect_events(self.ws, 1)

        current = await _js(self.ws, "window.location.href")
        self.logged_in = "/login" not in current

    async def navigate_and_collect_errors(self, route):
        """Nawiguje do trasy i zwraca liste bledow konsoli JS."""
        url = f"{BASE_URL}{route}"
        await _navigate(self.ws, url, timeout=25)
        await asyncio.sleep(2)  # Czas na Alpine init
        events = await _collect_events(self.ws, 2)
        return _extract_console_errors(events)

    async def js_eval(self, expression):
        return await _js(self.ws, expression)


@pytest.fixture(scope="module")
def cdp_session():
    """Fixture CDP - tworzy sesje, loguje i zamyka po testach."""
    session = CDPSession()

    async def _setup():
        await session.connect()
        await session.login()
        return session

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_setup())

    if not session.logged_in:
        loop.run_until_complete(session.close())
        loop.close()
        pytest.skip("Nie udalo sie zalogowac do aplikacji")

    yield session

    loop.run_until_complete(session.close())
    loop.close()


def _run(coro):
    """Uruchamia coroutine w event loopie."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---- Testy tras: brak bledow JS w konsoli ----

ROUTES_CORE = [
    "/",
    "/items",
    "/orders",
    "/history",
]

ROUTES_FORMS = [
    "/add_item",
    "/orders/add",
    "/import_invoice",
    "/deliveries",
]

ROUTES_ALLEGRO = [
    "/allegro/offers",
    "/offers-and-prices",
    "/allegro/price-check",
    "/discussions",
]

ROUTES_SETTINGS = [
    "/settings",
    "/sales/settings",
    "/logs",
]

ROUTES_SCAN = [
    "/stocktake",
    "/scan_barcode",
    "/scan_label",
    "/scan_logs",
]


@pytest.mark.e2e
@skip_no_cdp
@skip_no_password
class TestBrowserCore:
    """Trasy glowne - dashboard, produkty, zamowienia, historia."""

    @pytest.mark.parametrize("route", ROUTES_CORE)
    def test_no_js_errors(self, cdp_session, route):
        errors = _run(cdp_session.navigate_and_collect_errors(route))
        assert not errors, f"Bledy JS na {route}: {errors}"


@pytest.mark.e2e
@skip_no_cdp
@skip_no_password
class TestBrowserForms:
    """Formularze - dodawanie produktow, zamowien, dostaw."""

    @pytest.mark.parametrize("route", ROUTES_FORMS)
    def test_no_js_errors(self, cdp_session, route):
        errors = _run(cdp_session.navigate_and_collect_errors(route))
        assert not errors, f"Bledy JS na {route}: {errors}"


@pytest.mark.e2e
@skip_no_cdp
@skip_no_password
class TestBrowserAllegro:
    """Widoki Allegro - oferty, ceny, dyskusje."""

    @pytest.mark.parametrize("route", ROUTES_ALLEGRO)
    def test_no_js_errors(self, cdp_session, route):
        errors = _run(cdp_session.navigate_and_collect_errors(route))
        assert not errors, f"Bledy JS na {route}: {errors}"


@pytest.mark.e2e
@skip_no_cdp
@skip_no_password
class TestBrowserSettings:
    """Ustawienia i logi."""

    @pytest.mark.parametrize("route", ROUTES_SETTINGS)
    def test_no_js_errors(self, cdp_session, route):
        errors = _run(cdp_session.navigate_and_collect_errors(route))
        assert not errors, f"Bledy JS na {route}: {errors}"


@pytest.mark.e2e
@skip_no_cdp
@skip_no_password
class TestBrowserScan:
    """Skanowanie i remanent."""

    @pytest.mark.parametrize("route", ROUTES_SCAN)
    def test_no_js_errors(self, cdp_session, route):
        errors = _run(cdp_session.navigate_and_collect_errors(route))
        assert not errors, f"Bledy JS na {route}: {errors}"


@pytest.mark.e2e
@skip_no_cdp
@skip_no_password
class TestBrowserInteractions:
    """Testy interaktywne - klikanie elementow, toggle, dropdowny."""

    def test_navbar_dropdowns(self, cdp_session):
        """Klikniecie dropdownow w navbarze nie generuje bledow JS."""
        _run(cdp_session.navigate_and_collect_errors("/"))
        _run(cdp_session.js_eval("""
            document.querySelectorAll('.nav-item.dropdown .dropdown-toggle')
                .forEach(el => el.click())
        """))
        import asyncio as _aio
        errors = _run(_collect_events(cdp_session.ws, 1.5))
        js_errors = _extract_console_errors(errors)
        assert not js_errors, f"Bledy JS po kliknieciu dropdownow: {js_errors}"

    def test_add_item_color_toggle(self, cdp_session):
        """Zmiana koloru na 'Inny' w formularzu nie generuje bledow."""
        _run(cdp_session.navigate_and_collect_errors("/add_item"))
        _run(cdp_session.js_eval("""
        (function() {
            var sel = document.querySelector('select[name="color"]');
            if (sel) {
                sel.value = 'Inny';
                sel.dispatchEvent(new Event('input', {bubbles: true}));
                sel.dispatchEvent(new Event('change', {bubbles: true}));
            }
        })()
        """))
        import asyncio as _aio
        errors = _run(_collect_events(cdp_session.ws, 1))
        js_errors = _extract_console_errors(errors)
        assert not js_errors, f"Bledy JS po zmianie koloru: {js_errors}"

    def test_settings_password_toggle(self, cdp_session):
        """Toggle widocznosci hasla w ustawieniach nie generuje bledow."""
        _run(cdp_session.navigate_and_collect_errors("/settings"))
        _run(cdp_session.js_eval("""
        (function() {
            var toggles = document.querySelectorAll('[\\\\@click*="show"]');
            toggles.forEach(function(t) { t.click(); });
        })()
        """))
        import asyncio as _aio
        errors = _run(_collect_events(cdp_session.ws, 1))
        js_errors = _extract_console_errors(errors)
        assert not js_errors, f"Bledy JS po toggle hasla: {js_errors}"
