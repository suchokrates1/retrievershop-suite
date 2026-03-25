#!/usr/bin/env python3
"""
Test E2E przez przegladarke CDP - przechodzi przez kazdy widok aplikacji,
loguje sie, klika elementy i zbiera bledy konsoli JS.

Wymaga kontenera Chromium z CDP na minipc:9223.

Uzycie:
    python scripts/e2e_browser_test.py --password HASLO
    python scripts/e2e_browser_test.py --password HASLO --base-url https://magazyn.retrievershop.pl
"""

import asyncio
import json
import sys
import argparse
import urllib.request
import time
from dataclasses import dataclass, field
from typing import Optional

CDP_HOST = "192.168.31.147"
CDP_PORT = 9223
BASE_URL = "https://magazyn.retrievershop.pl"
USERNAME = "admin"

# ---- Trasy do przetestowania (GET only - bez modyfikacji danych) ----
GET_ROUTES = [
    "/",
    "/items",
    "/orders",
    "/sales",
    "/history",
    "/settings",
    "/sales/settings",
    "/logs",
    "/allegro/offers",
    "/offers-and-prices",
    "/discussions",
    "/add_item",
    "/orders/add",
    "/import_invoice",
    "/deliveries",
    "/stocktake",
    "/scan_barcode",
    "/scan_label",
    "/scan_logs",
]

# Trasy wymagajace parametrow - sprawdzimy po zalogowaniu
PARAM_ROUTES_TEMPLATES = [
    # Pobierzemy dynamicznie pierwszy produkt/zamowienie
]


@dataclass
class ConsoleEntry:
    level: str
    text: str
    url: str
    route: str


@dataclass
class TestResult:
    route: str
    status: str  # "ok", "error", "redirect", "timeout"
    http_status: Optional[int] = None
    load_time_ms: int = 0
    console_errors: list = field(default_factory=list)
    console_warnings: list = field(default_factory=list)
    js_exceptions: list = field(default_factory=list)
    notes: str = ""


# ---- Narzedzia CDP ----

_msg_counter = 0


def next_id():
    global _msg_counter
    _msg_counter += 1
    return _msg_counter


async def cdp_send(ws, method, params=None):
    mid = next_id()
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    return mid


async def cdp_call(ws, method, params=None, timeout=15):
    mid = await cdp_send(ws, method, params)
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
    raise TimeoutError(f"CDP timeout for {method}")


async def collect_events(ws, duration=0.5):
    """Zbiera uzbierane eventy przez podany czas."""
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


async def get_new_page_ws(host, port):
    """Tworzy nowa karte i zwraca websocket URL."""
    url = f"http://{host}:{port}/json/new"
    loop = asyncio.get_event_loop()

    def create():
        req = urllib.request.Request(url, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    page = await loop.run_in_executor(None, create)
    return page["id"], page["webSocketDebuggerUrl"]


async def close_page(host, port, page_id):
    """Zamyka karte."""
    url = f"http://{host}:{port}/json/close/{page_id}"
    loop = asyncio.get_event_loop()

    def close():
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read()
        except Exception:
            pass

    await loop.run_in_executor(None, close)


async def navigate_and_wait(ws, url, timeout=20):
    """Nawiguje i czeka na zaladowanie strony. Zwraca czas ladowania."""
    await cdp_call(ws, "Page.enable")
    t0 = time.monotonic()
    await cdp_call(ws, "Page.navigate", {"url": url})

    deadline = t0 + timeout
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            if data.get("method") == "Page.loadEventFired":
                return int((time.monotonic() - t0) * 1000)
            # Zbieraj eventy konsoli w miedzyczasie
        except asyncio.TimeoutError:
            continue

    return int((time.monotonic() - t0) * 1000)


async def get_current_url(ws):
    """Pobiera aktualny URL strony."""
    result = await cdp_call(ws, "Runtime.evaluate", {
        "expression": "window.location.href"
    })
    return result.get("result", {}).get("value", "")


async def get_page_title(ws):
    result = await cdp_call(ws, "Runtime.evaluate", {
        "expression": "document.title"
    })
    return result.get("result", {}).get("value", "")


async def click_element(ws, selector, timeout=5):
    """Klika element po selektorze CSS. Zwraca True jesli udalo sie."""
    result = await cdp_call(ws, "Runtime.evaluate", {
        "expression": f"""
        (function() {{
            var el = document.querySelector('{selector}');
            if (!el) return 'not_found';
            el.click();
            return 'clicked';
        }})()
        """
    })
    val = result.get("result", {}).get("value", "")
    return val == "clicked"


async def fill_input(ws, selector, value):
    """Wypelnia pole formularza."""
    await cdp_call(ws, "Runtime.evaluate", {
        "expression": f"""
        (function() {{
            var el = document.querySelector('{selector}');
            if (!el) return 'not_found';
            el.value = {json.dumps(value)};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return 'filled';
        }})()
        """
    })


async def get_element_count(ws, selector):
    """Zwraca liczbe elementow pasujacych do selektora."""
    result = await cdp_call(ws, "Runtime.evaluate", {
        "expression": f"document.querySelectorAll('{selector}').length"
    })
    return result.get("result", {}).get("value", 0)


async def get_first_link_href(ws, selector):
    """Pobiera href pierwszego linku pasujacego do selektora."""
    result = await cdp_call(ws, "Runtime.evaluate", {
        "expression": f"""
        (function() {{
            var el = document.querySelector('{selector}');
            return el ? el.href || el.getAttribute('href') : null;
        }})()
        """
    })
    return result.get("result", {}).get("value")


# ---- Glowna logika testow ----

class E2ETest:
    def __init__(self, host, port, base_url, username, password):
        self.host = host
        self.port = port
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.results = []
        self.console_errors_all = []
        self.ws = None
        self.page_id = None

    async def setup(self):
        """Tworzy nowa karte i wlacza zbieranie konsoli."""
        import websockets
        self.page_id, ws_url = await get_new_page_ws(self.host, self.port)
        # Podmien localhost na faktyczny host
        ws_url = ws_url.replace("localhost", self.host).replace("127.0.0.1", self.host)
        self.ws = await websockets.connect(ws_url, max_size=10 * 1024 * 1024)
        # Wlacz zbieranie konsoli i wyjatkow JS
        await cdp_call(self.ws, "Console.enable")
        await cdp_call(self.ws, "Runtime.enable")
        await cdp_call(self.ws, "Log.enable")
        print(f"Utworzono karte testowa: {self.page_id}")

    async def teardown(self):
        """Zamyka karte testowa."""
        if self.ws:
            await self.ws.close()
        if self.page_id:
            await close_page(self.host, self.port, self.page_id)
            print(f"Zamknieto karte testowa: {self.page_id}")

    async def collect_console(self, route):
        """Zbiera bledy konsoli po zaladowaniu strony."""
        errors = []
        warnings = []
        exceptions = []

        events = await collect_events(self.ws, duration=1.5)
        for ev in events:
            method = ev.get("method", "")
            params = ev.get("params", {})

            if method == "Console.messageAdded":
                msg = params.get("message", {})
                level = msg.get("level", "")
                text = msg.get("text", "")
                url = msg.get("url", "")
                if level == "error":
                    entry = ConsoleEntry(level, text, url, route)
                    errors.append(entry)
                    self.console_errors_all.append(entry)
                elif level == "warning":
                    warnings.append(ConsoleEntry(level, text, url, route))

            elif method == "Runtime.consoleAPICalled":
                call_type = params.get("type", "")
                args = params.get("args", [])
                text = " ".join(a.get("value", a.get("description", "")) for a in args)
                if call_type == "error":
                    entry = ConsoleEntry("error", text, "", route)
                    errors.append(entry)
                    self.console_errors_all.append(entry)
                elif call_type == "warning":
                    warnings.append(ConsoleEntry("warning", text, "", route))

            elif method == "Runtime.exceptionThrown":
                exc = params.get("exceptionDetails", {})
                text = exc.get("text", "")
                exc_obj = exc.get("exception", {})
                desc = exc_obj.get("description", exc_obj.get("value", ""))
                full = f"{text}: {desc}" if desc else text
                entry = ConsoleEntry("exception", full, "", route)
                exceptions.append(entry)
                self.console_errors_all.append(entry)

            elif method == "Log.entryAdded":
                entry_data = params.get("entry", {})
                level = entry_data.get("level", "")
                text = entry_data.get("text", "")
                url = entry_data.get("url", "")
                if level == "error":
                    entry = ConsoleEntry("error", text, url, route)
                    errors.append(entry)
                    self.console_errors_all.append(entry)

        return errors, warnings, exceptions

    async def login(self):
        """Loguje sie do aplikacji."""
        print(f"\n--- Logowanie jako {self.username} ---")
        url = f"{self.base_url}/login"
        load_ms = await navigate_and_wait(self.ws, url)
        await asyncio.sleep(1)

        current = await get_current_url(self.ws)
        if "/login" not in current:
            print(f"  Juz zalogowany (przekierowanie do {current})")
            return True

        # Pobierz CSRF token
        csrf = await cdp_call(self.ws, "Runtime.evaluate", {
            "expression": """
            (function() {
                var el = document.querySelector('input[name="csrf_token"]');
                return el ? el.value : null;
            })()
            """
        })
        csrf_token = csrf.get("result", {}).get("value")

        # Wypelnij formularz
        await fill_input(self.ws, 'input[name="username"]', self.username)
        await fill_input(self.ws, 'input[name="password"]', self.password)
        await asyncio.sleep(0.3)

        # Wyslij formularz
        await cdp_call(self.ws, "Runtime.evaluate", {
            "expression": "document.querySelector('form').submit()"
        })
        await asyncio.sleep(2)

        # Zbierz eventy (nawigacja po submit)
        await collect_events(self.ws, duration=2)

        current = await get_current_url(self.ws)
        if "/login" in current:
            print("  BLAD: Logowanie nie powiodlo sie!")
            return False

        title = await get_page_title(self.ws)
        print(f"  Zalogowano. Strona: {title}")
        return True

    async def test_route(self, route):
        """Testuje pojedyncza trase."""
        url = f"{self.base_url}{route}"
        print(f"  Testuje: {route:<35}", end="", flush=True)

        try:
            load_ms = await navigate_and_wait(self.ws, url, timeout=20)
        except Exception as e:
            result = TestResult(route=route, status="timeout", notes=str(e))
            self.results.append(result)
            print(f"  TIMEOUT  ({e})")
            return result

        # Poczekaj na Alpine/JS
        await asyncio.sleep(1.5)

        # Zbierz bledy konsoli
        errors, warnings, exceptions = await self.collect_console(route)

        # Sprawdz przekierowanie (np. na login)
        current = await get_current_url(self.ws)
        if "/login" in current and route != "/login":
            result = TestResult(
                route=route, status="redirect",
                load_time_ms=load_ms,
                notes="Przekierowanie na login - sesja wygasla?"
            )
            self.results.append(result)
            print(f"  REDIRECT (login)")
            return result

        status = "ok" if not errors and not exceptions else "error"
        result = TestResult(
            route=route, status=status,
            load_time_ms=load_ms,
            console_errors=errors,
            console_warnings=warnings,
            js_exceptions=exceptions
        )
        self.results.append(result)

        err_count = len(errors) + len(exceptions)
        warn_count = len(warnings)
        status_str = "OK" if status == "ok" else f"BLEDY: {err_count}"
        extra = f" ({warn_count} warn)" if warn_count else ""
        print(f"  {load_ms:>5}ms  {status_str}{extra}")
        return result

    async def test_dynamic_routes(self):
        """Testuje trasy z parametrami - pobiera dane dynamicznie."""
        print("\n--- Trasy dynamiczne ---")

        # Pobierz pierwszy produkt
        await navigate_and_wait(self.ws, f"{self.base_url}/items")
        await asyncio.sleep(1)
        product_link = await get_first_link_href(self.ws, "table tbody tr td a[href*='/product/']")
        if product_link:
            # Wyciagnij sciezke
            from urllib.parse import urlparse
            path = urlparse(product_link).path
            await self.test_route(path)
        else:
            print("  Brak produktow do przetestowania /product/<id>")
        await collect_events(self.ws, 0.5)

        # Pobierz pierwsze zamowienie
        await navigate_and_wait(self.ws, f"{self.base_url}/orders")
        await asyncio.sleep(1)
        order_link = await get_first_link_href(self.ws, "tr.clickable-row[data-href]")
        if not order_link:
            # Sprobuj inaczej
            order_link = await cdp_call(self.ws, "Runtime.evaluate", {
                "expression": """
                (function() {
                    var row = document.querySelector('tr[data-href]');
                    if (row) return row.getAttribute('data-href');
                    var link = document.querySelector('table tbody tr td a[href*="/order/"]');
                    return link ? link.href : null;
                })()
                """
            })
            order_link = order_link.get("result", {}).get("value")

        if order_link:
            from urllib.parse import urlparse
            if order_link.startswith("http"):
                path = urlparse(order_link).path
            else:
                path = order_link
            await self.test_route(path)
        else:
            print("  Brak zamowien do przetestowania /order/<id>")
        await collect_events(self.ws, 0.5)

    async def test_click_interactions(self):
        """Klika interaktywne elementy i sprawdza bledy."""
        print("\n--- Testy interaktywne (klikanie) ---")

        # Strona glowna - kliknij dropdowny w navbarze
        await navigate_and_wait(self.ws, f"{self.base_url}/")
        await asyncio.sleep(1)

        # Kliknij dropdown "Magazyn" w nav
        dropdown_count = await get_element_count(self.ws, ".nav-item.dropdown .dropdown-toggle")
        if dropdown_count > 0:
            for i in range(dropdown_count):
                clicked = await cdp_call(self.ws, "Runtime.evaluate", {
                    "expression": f"""
                    (function() {{
                        var items = document.querySelectorAll('.nav-item.dropdown .dropdown-toggle');
                        if (items[{i}]) {{ items[{i}].click(); return 'clicked'; }}
                        return 'not_found';
                    }})()
                    """
                })
                await asyncio.sleep(0.5)
            errors, warnings, exceptions = await self.collect_console("/navbar-dropdowns")
            err_count = len(errors) + len(exceptions)
            print(f"  Navbar dropdowny ({dropdown_count}x):     {'OK' if err_count == 0 else f'BLEDY: {err_count}'}")

        # Strona items - paginacja
        await navigate_and_wait(self.ws, f"{self.base_url}/items")
        await asyncio.sleep(1)
        per_page_exists = await get_element_count(self.ws, "select[name='per_page'], select.per-page-select")
        if per_page_exists:
            await cdp_call(self.ws, "Runtime.evaluate", {
                "expression": """
                (function() {
                    var sel = document.querySelector('select[name="per_page"]');
                    if (!sel) sel = document.querySelector('select');
                    if (sel && sel.options.length > 1) {
                        sel.value = sel.options[1].value;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                })()
                """
            })
            await asyncio.sleep(2)
            errors, warnings, exceptions = await self.collect_console("/items-perpage")
            err_count = len(errors) + len(exceptions)
            print(f"  Items per_page change:            {'OK' if err_count == 0 else f'BLEDY: {err_count}'}")

        # add_item - toggle koloru
        await navigate_and_wait(self.ws, f"{self.base_url}/add_item")
        await asyncio.sleep(1)
        await cdp_call(self.ws, "Runtime.evaluate", {
            "expression": """
            (function() {
                var sel = document.querySelector('select[name="color"]');
                if (sel) {
                    for (var i = 0; i < sel.options.length; i++) {
                        if (sel.options[i].value === 'Inny') {
                            sel.value = 'Inny';
                            sel.dispatchEvent(new Event('input', {bubbles: true}));
                            sel.dispatchEvent(new Event('change', {bubbles: true}));
                            break;
                        }
                    }
                }
            })()
            """
        })
        await asyncio.sleep(0.5)
        errors, warnings, exceptions = await self.collect_console("/add_item-color-toggle")
        err_count = len(errors) + len(exceptions)
        print(f"  add_item kolor 'Inny':            {'OK' if err_count == 0 else f'BLEDY: {err_count}'}")

        # settings - toggle hasla
        await navigate_and_wait(self.ws, f"{self.base_url}/settings")
        await asyncio.sleep(1)
        toggle_count = await get_element_count(self.ws, ".input-group .bi-eye, .input-group .bi-eye-slash, [x-data] .bi-eye")
        if toggle_count > 0:
            await cdp_call(self.ws, "Runtime.evaluate", {
                "expression": """
                (function() {
                    var toggles = document.querySelectorAll('.input-group span[style*=cursor], .input-group [\\\\@click]');
                    toggles.forEach(function(t) { t.click(); });
                    return toggles.length;
                })()
                """
            })
            await asyncio.sleep(0.5)
            errors, warnings, exceptions = await self.collect_console("/settings-password-toggle")
            err_count = len(errors) + len(exceptions)
            print(f"  Settings toggle hasla ({toggle_count}x):    {'OK' if err_count == 0 else f'BLEDY: {err_count}'}")

        # orders - search enter
        await navigate_and_wait(self.ws, f"{self.base_url}/orders")
        await asyncio.sleep(1)
        search_exists = await get_element_count(self.ws, "input[name='search'], input[type='search']")
        if search_exists:
            await fill_input(self.ws, "input[name='search'], input[type='search']", "test123")
            await asyncio.sleep(0.5)
            errors, warnings, exceptions = await self.collect_console("/orders-search")
            err_count = len(errors) + len(exceptions)
            print(f"  Orders wyszukiwanie:              {'OK' if err_count == 0 else f'BLEDY: {err_count}'}")

        # history - filtr
        await navigate_and_wait(self.ws, f"{self.base_url}/history")
        await asyncio.sleep(1)
        filter_exists = await get_element_count(self.ws, "input[x-model], input[placeholder*='Szukaj'], input[placeholder*='szukaj'], input#searchInput")
        if filter_exists:
            await cdp_call(self.ws, "Runtime.evaluate", {
                "expression": """
                (function() {
                    var inp = document.querySelector('input[x-model], input[placeholder*="Szukaj"], input[placeholder*="szukaj"], input#searchInput');
                    if (inp) {
                        inp.value = 'test';
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                    }
                })()
                """
            })
            await asyncio.sleep(0.5)
            errors, warnings, exceptions = await self.collect_console("/history-filter")
            err_count = len(errors) + len(exceptions)
            print(f"  History filtr:                    {'OK' if err_count == 0 else f'BLEDY: {err_count}'}")

    async def run(self):
        """Uruchamia pelny zestaw testow."""
        print("=" * 60)
        print("  TEST E2E PRZEGLADARKI - MAGAZYN")
        print("=" * 60)
        print(f"CDP: {self.host}:{self.port}")
        print(f"App: {self.base_url}")
        print(f"User: {self.username}")

        await self.setup()

        try:
            # 1. Logowanie
            logged_in = await self.login()
            if not logged_in:
                print("\nNie mozna kontynuowac bez logowania!")
                return

            # 2. Przetestuj wszystkie trasy GET
            print("\n--- Trasy statyczne ---")
            for route in GET_ROUTES:
                await self.test_route(route)
                # Sprawdz czy sesja nie wygasla
                current = await get_current_url(self.ws)
                if "/login" in current and route != "/login":
                    print("\n  SESJA WYGASLA - ponowne logowanie...")
                    await self.login()

            # 3. Trasy dynamiczne
            await self.test_dynamic_routes()

            # 4. Testy interaktywne
            await self.test_click_interactions()

        finally:
            await self.teardown()

        # Raport koncowy
        self.print_report()

    def print_report(self):
        """Drukuje raport koncowy."""
        print("\n" + "=" * 60)
        print("  RAPORT KONCOWY")
        print("=" * 60)

        ok_count = sum(1 for r in self.results if r.status == "ok")
        err_count = sum(1 for r in self.results if r.status == "error")
        redirect_count = sum(1 for r in self.results if r.status == "redirect")
        timeout_count = sum(1 for r in self.results if r.status == "timeout")
        total = len(self.results)

        print(f"\nWyniki: {total} tras przetestowanych")
        print(f"  OK:           {ok_count}")
        print(f"  Bledy JS:     {err_count}")
        print(f"  Redirect:     {redirect_count}")
        print(f"  Timeout:      {timeout_count}")

        if self.console_errors_all:
            print(f"\n--- Wszystkie bledy konsoli ({len(self.console_errors_all)}) ---")
            # Deduplikacja
            seen = set()
            for entry in self.console_errors_all:
                key = (entry.level, entry.text[:100])
                if key in seen:
                    continue
                seen.add(key)
                route = entry.route
                text = entry.text[:200] if len(entry.text) > 200 else entry.text
                print(f"\n  [{entry.level.upper()}] {route}")
                print(f"    {text}")
                if entry.url:
                    print(f"    URL: {entry.url}")
        else:
            print("\nBrak bledow konsoli JS!")

        # Trasy z bledami
        error_routes = [r for r in self.results if r.status == "error"]
        if error_routes:
            print(f"\n--- Trasy z bledami ---")
            for r in error_routes:
                err_texts = [e.text[:80] for e in r.console_errors + r.js_exceptions]
                print(f"  {r.route}: {', '.join(err_texts)}")

        print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Test E2E przez przegladarke CDP")
    parser.add_argument("--password", required=True, help="Haslo do logowania")
    parser.add_argument("--username", default=USERNAME, help="Nazwa uzytkownika")
    parser.add_argument("--base-url", default=BASE_URL, help="URL aplikacji")
    parser.add_argument("--cdp-host", default=CDP_HOST, help="Host CDP")
    parser.add_argument("--cdp-port", type=int, default=CDP_PORT, help="Port CDP")
    args = parser.parse_args()

    test = E2ETest(
        host=args.cdp_host,
        port=args.cdp_port,
        base_url=args.base_url,
        username=args.username,
        password=args.password,
    )

    asyncio.run(test.run())


if __name__ == "__main__":
    main()
