"""Testy responsywnosci UI (brak poziomego overflow) dla widokow P0."""
import pytest

playwright = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright nie jest zainstalowany w tym srodowisku testowym",
)
Page = playwright.Page

pytestmark = pytest.mark.e2e

VIEWPORTS = {
    "mobile": {"width": 360, "height": 800},
    "tablet": {"width": 768, "height": 1024},
    "desktop": {"width": 1280, "height": 900},
}


def _assert_no_horizontal_overflow(page: Page, *, label: str, viewport_name: str, vp: dict) -> None:
    page.set_viewport_size(vp)
    page.wait_for_load_state("networkidle")
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert not overflow, (
        f"{label} ma poziomy overflow na {viewport_name} ({vp['width']}x{vp['height']})"
    )


class TestHomePage:
    @pytest.mark.parametrize("viewport_name", VIEWPORTS)
    def test_home_no_overflow(self, logged_in_page: Page, live_url: str, viewport_name: str):
        logged_in_page.goto(f"{live_url}/")
        _assert_no_horizontal_overflow(
            logged_in_page,
            label="Strona glowna",
            viewport_name=viewport_name,
            vp=VIEWPORTS[viewport_name],
        )


class TestStatsDashboard:
    @pytest.mark.parametrize("viewport_name", VIEWPORTS)
    def test_stats_no_overflow(self, logged_in_page: Page, live_url: str, viewport_name: str):
        logged_in_page.goto(f"{live_url}/stats")
        _assert_no_horizontal_overflow(
            logged_in_page,
            label="Dashboard statystyk",
            viewport_name=viewport_name,
            vp=VIEWPORTS[viewport_name],
        )


class TestOrdersList:
    @pytest.mark.parametrize("viewport_name", VIEWPORTS)
    def test_orders_no_overflow(self, logged_in_page: Page, live_url: str, viewport_name: str):
        logged_in_page.goto(f"{live_url}/orders")
        _assert_no_horizontal_overflow(
            logged_in_page,
            label="Lista zamowien",
            viewport_name=viewport_name,
            vp=VIEWPORTS[viewport_name],
        )


class TestItems:
    @pytest.mark.parametrize("viewport_name", VIEWPORTS)
    def test_items_no_overflow(self, logged_in_page: Page, live_url: str, viewport_name: str):
        logged_in_page.goto(f"{live_url}/items")
        _assert_no_horizontal_overflow(
            logged_in_page,
            label="Lista przedmiotow",
            viewport_name=viewport_name,
            vp=VIEWPORTS[viewport_name],
        )
