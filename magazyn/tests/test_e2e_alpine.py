"""Testy integralnosci Alpine.js w szablonach HTML.

Sprawdzaja czy renderowany HTML jest poprawny pod katem Alpine.js:
- CSP zawiera 'unsafe-eval' wymagany przez Alpine
- Kazdemu x-data="komponent()" towarzyszy rejestracja Alpine.data()
- Atrybuty x-data nie zawieraja zepsutych cudzyslowow (problem tojson)
- Skrypt Alpine jest ladowany w kazdym szablonie
"""

import re

import pytest

from magazyn.models.users import User
from werkzeug.security import generate_password_hash


# Trasy GET do przetestowania (nie modyfikuja danych)
READONLY_ROUTES = [
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


@pytest.fixture(autouse=True)
def _seed_user(app_mod):
    """Tworzy uzytkownika testowego dla wszystkich testow w module."""
    hashed = generate_password_hash("secret")
    with app_mod.get_session() as db:
        db.add(User(username="tester", password=hashed))
        db.commit()


# ---- CSP ----


def test_csp_allows_alpine_unsafe_eval(client, login):
    """CSP musi zawierac 'unsafe-eval' w script-src zeby Alpine.js dzialal."""
    resp = client.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "'unsafe-eval'" in csp, (
        "CSP nie zawiera 'unsafe-eval' w script-src - Alpine.js nie bedzie dzialac"
    )


def test_csp_allows_alpine_cdn(client, login):
    """CSP musi zezwalac na cdn.jsdelivr.net skad ladowany jest Alpine."""
    resp = client.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "cdn.jsdelivr.net" in csp


# ---- Alpine CDN ----


def test_alpine_script_loaded(client, login):
    """Alpine.js musi byc ladowany w base.html."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert "alpinejs" in html.lower() or "alpine" in html.lower(), (
        "Brak tagu script ladujacego Alpine.js"
    )


# ---- x-data bez zepsutych cudzyslowow ----


_BROKEN_XDATA_RE = re.compile(r'x-data="[^"]*"[^"]*"')


@pytest.mark.parametrize("route", READONLY_ROUTES)
def test_xdata_no_broken_quotes(client, login, route):
    """x-data nie powinno zawierac zepsutych cudzyslowow (problem z tojson na stringach)."""
    resp = client.get(route)
    if resp.status_code != 200:
        pytest.skip(f"Trasa {route} zwrocila {resp.status_code}")
    html = resp.get_data(as_text=True)
    # Szukaj atrybutow x-data ktore maja podwojne cudzyslowy w srodku
    matches = _BROKEN_XDATA_RE.findall(html)
    # Odfiltruj false positives (np. inne atrybuty po x-data na tym samym elemencie)
    broken = []
    for match in matches:
        # Jesli po zamknieciu x-data jest normalny atrybut HTML to OK
        # Zepsute: x-data="wakeLock("false")" - cudzyslowy JSON w srodku
        if '("' in match or "('" in match:
            broken.append(match)
    assert not broken, f"Zepsute x-data na {route}: {broken}"


# ---- Alpine.data() rejestracja ----


_XDATA_COMPONENT_RE = re.compile(r'x-data="(\w+)\(')
_ALPINE_DATA_RE = re.compile(r"Alpine\.data\(['\"](\w+)['\"]")


@pytest.mark.parametrize("route", READONLY_ROUTES)
def test_alpine_components_registered(client, login, route):
    """Kazdy x-data="komponent()" musi miec odpowiadajacy Alpine.data('komponent')."""
    resp = client.get(route)
    if resp.status_code != 200:
        pytest.skip(f"Trasa {route} zwrocila {resp.status_code}")
    html = resp.get_data(as_text=True)

    # Znajdz uzycia komponentow w x-data
    used_components = set(_XDATA_COMPONENT_RE.findall(html))
    # Znajdz zarejestrowane komponenty
    registered_components = set(_ALPINE_DATA_RE.findall(html))

    missing = used_components - registered_components
    assert not missing, (
        f"Niezarejestrowane komponenty Alpine na {route}: {missing}. "
        f"Uzyto: {used_components}, zarejestrowano: {registered_components}"
    )


# ---- Brak inline JS ktory powinien byc Alpine ----


# ---- Alpine main x-data scope ----


def test_main_has_xdata_scope(client, login):
    """Element <main> musi miec x-data aby dyrektywy Alpine w content dzialaly."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert re.search(r"<main\b[^>]*\bx-data\b", html), (
        "<main> nie ma x-data - dyrektywy Alpine w bloku content nie beda dzialac"
    )


# ---- Dyrektywy Alpine wewnatrz x-data scope ----


_ALPINE_DIRECTIVE_RE = re.compile(
    r"<(\w+)\b[^>]*(?:@click|@change|@keydown|@submit|@input|x-model|x-show|x-text)\b"
)
_XDATA_RE = re.compile(r"\bx-data\b")


@pytest.mark.parametrize("route", READONLY_ROUTES)
def test_alpine_directives_have_scope(client, login, route):
    """Dyrektywy Alpine (@click, x-model, etc.) musza byc wewnatrz elementu z x-data."""
    resp = client.get(route)
    if resp.status_code != 200:
        pytest.skip(f"Trasa {route} zwrocila {resp.status_code}")
    html = resp.get_data(as_text=True)

    # Sprawdz czy <main> (albo <body>) ma x-data jako globalny scope
    has_global_scope = bool(re.search(r"<main\b[^>]*\bx-data\b", html))

    if has_global_scope:
        return  # Globalny scope — wszystkie dyrektywy automatycznie dzialaja

    # Bez globalnego scope — kazda dyrektywa musi byc wewnatrz lokalnego x-data
    directives = _ALPINE_DIRECTIVE_RE.findall(html)
    if not directives:
        return  # Brak dyrektyw — OK

    # Jesli sa dyrektywy a nie ma globalnego scope — blad
    assert False, (
        f"Trasa {route} uzywa dyrektyw Alpine ale <main> nie ma x-data. "
        f"Dyrektywy moga nie dzialac."
    )


# ---- Brak inline JS ktory powinien byc Alpine ----


_GETELEMENTBYID_RE = re.compile(r"document\.getElementById\(")
_QUERYSELECTOR_RE = re.compile(r"document\.querySelector\(")


@pytest.mark.parametrize("route", READONLY_ROUTES)
def test_no_orphan_vanilla_js_handlers(client, login, route):
    """Szablony nie powinny mieszac Alpine z getElementById/querySelector do tego samego celu.

    Test ostrzeleniowy - wykrywa szablony gdzie Alpine jest uzyty ale rownoczesnie
    sa vanilla JS handlery ktore mogly byc przeoczone.
    """
    resp = client.get(route)
    if resp.status_code != 200:
        pytest.skip(f"Trasa {route} zwrocila {resp.status_code}")
    html = resp.get_data(as_text=True)

    has_alpine = "x-data" in html
    if not has_alpine:
        return  # Szablon bez Alpine - nie sprawdzamy

    # Licz vanilla JS patterny w bloku <script>
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.+?)</script>", html, re.S)
    vanilla_count = 0
    for script in scripts:
        # Pomijaj skrypty Alpine.data - te sa OK
        if "Alpine.data" in script or "alpine:init" in script:
            continue
        # Pomijaj CDN scripts (src=)
        if not script.strip():
            continue
        vanilla_count += len(_GETELEMENTBYID_RE.findall(script))
        vanilla_count += len(_QUERYSELECTOR_RE.findall(script))

    # Po migracji Fazy 5 dashboard nie ma juz vanilla JS selectorow
    max_allowed = 3
    assert vanilla_count <= max_allowed, (
        f"Trasa {route} uzywa Alpine ale ma {vanilla_count} "
        f"vanilla JS selectorow - moze brakuje migracji?"
    )


# ---- Walidacja odpowiedzi HTTP ----


@pytest.mark.parametrize("route", READONLY_ROUTES)
def test_route_returns_200(client, login, route):
    """Kazda trasa GET powinna zwrocic 200."""
    resp = client.get(route)
    assert resp.status_code == 200, (
        f"Trasa {route} zwrocila {resp.status_code} zamiast 200"
    )
