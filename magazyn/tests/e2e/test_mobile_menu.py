"""Smoke testy E2E dla mobile menu.

Weryfikuje:
- otwarcie i zamkniecie menu hamburgerowego
- zamkniecie po kliknieciu w backdrop
- zamkniecie po wyborze pozycji menu
- brak konfliktu z przewijaniem strony
- blokade scrolla body przy otwartym menu
"""
import pytest
import re
from playwright.sync_api import Page, expect


MOBILE_VIEWPORT = {"width": 360, "height": 800}


@pytest.fixture(autouse=True)
def _mobile_viewport(logged_in_page: Page):
    """Ustawia viewport mobilny dla wszystkich testow w module."""
    logged_in_page.set_viewport_size(MOBILE_VIEWPORT)


class TestMobileMenu:
    """Testy mobile menu (hamburger)."""

    def _open_menu(self, page: Page):
        """Otwiera menu mobilne."""
        page.wait_for_function("() => typeof Alpine !== 'undefined'", timeout=10000)
        page.wait_for_timeout(500)
        hamburger = page.locator("button.btn-ghost.md\\:hidden")
        hamburger.scroll_into_view_if_needed()
        hamburger.click(force=True)
        page.wait_for_timeout(600)

    def test_hamburger_visible_on_mobile(self, logged_in_page: Page, live_url: str):
        """Przycisk hamburgera jest widoczny na mobile."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        hamburger = logged_in_page.locator("button.btn-ghost.md\\:hidden")
        expect(hamburger).to_be_visible()

    def test_menu_opens_on_click(self, logged_in_page: Page, live_url: str):
        """Klikniecie hamburgera otwiera mobile menu."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")

        self._open_menu(logged_in_page)

        has_open = logged_in_page.evaluate(
            "() => document.querySelector('.mobile-menu').classList.contains('open')"
        )
        assert has_open, "Mobile menu powinno miec klase 'open' po kliknieciu hamburgera"

    def test_backdrop_visible_when_open(self, logged_in_page: Page, live_url: str):
        """Backdrop jest widoczny gdy menu otwarte."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        self._open_menu(logged_in_page)

        backdrop = logged_in_page.locator(".mobile-menu-backdrop")
        expect(backdrop).to_have_class(re.compile(r"open"))

    def test_close_via_backdrop(self, logged_in_page: Page, live_url: str):
        """Klikniecie w backdrop zamyka menu."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        self._open_menu(logged_in_page)

        backdrop = logged_in_page.locator(".mobile-menu-backdrop")
        backdrop.click(position={"x": 20, "y": 400})
        logged_in_page.wait_for_timeout(400)

        menu = logged_in_page.locator(".mobile-menu")
        expect(menu).not_to_have_class("open")

    def test_close_via_close_button(self, logged_in_page: Page, live_url: str):
        """Klikniecie X zamyka menu."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        self._open_menu(logged_in_page)

        close_btn = logged_in_page.locator(".mobile-menu button[aria-label='Zamknij']")
        close_btn.click()
        logged_in_page.wait_for_timeout(400)

        menu = logged_in_page.locator(".mobile-menu")
        expect(menu).not_to_have_class("open")

    def test_close_on_link_click(self, logged_in_page: Page, live_url: str):
        """Klikniecie pozycji menu zamyka panel."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        self._open_menu(logged_in_page)

        first_link = logged_in_page.locator(".mobile-menu a").first
        first_link.click()
        logged_in_page.wait_for_timeout(500)

        menu = logged_in_page.locator(".mobile-menu")
        expect(menu).not_to_have_class("open")

    def test_body_scroll_locked_when_open(self, logged_in_page: Page, live_url: str):
        """Body ma klase menu-open (overflow: hidden) gdy menu otwarte."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        self._open_menu(logged_in_page)

        has_class = logged_in_page.evaluate(
            "() => document.body.classList.contains('menu-open')"
        )
        assert has_class, "Body powinno miec klase 'menu-open' przy otwartym menu"

    def test_body_scroll_unlocked_when_closed(self, logged_in_page: Page, live_url: str):
        """Body nie ma klasy menu-open po zamknieciu."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        self._open_menu(logged_in_page)

        close_btn = logged_in_page.locator(".mobile-menu button[aria-label='Zamknij']")
        close_btn.click()
        logged_in_page.wait_for_timeout(400)

        has_class = logged_in_page.evaluate(
            "() => document.body.classList.contains('menu-open')"
        )
        assert not has_class, "Body nie powinno miec klasy 'menu-open' po zamknieciu"

    def test_all_menu_items_present(self, logged_in_page: Page, live_url: str):
        """Wszystkie kluczowe pozycje menu sa obecne."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        self._open_menu(logged_in_page)

        expected_labels = [
            "Strona",
            "Statystyki",
            "Przedmioty",
            "Zamówienia",
            "Oferty Allegro",
            "Raporty cenowe",
            "Ustawienia",
            "Wyloguj",
        ]

        menu_text = logged_in_page.locator(".mobile-menu").inner_text()
        for label in expected_labels:
            assert label in menu_text, f"Brak pozycji '{label}' w mobile menu"

    def test_no_horizontal_overflow_with_menu(self, logged_in_page: Page, live_url: str):
        """Menu nie powoduje poziomego overflow strony."""
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")
        self._open_menu(logged_in_page)

        overflow = logged_in_page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, "Mobile menu powoduje poziomy overflow"


