"""E2E: reczne zamowienia OLX (dodawanie, tracking, status wydrukowano)."""

import pytest
from playwright.sync_api import Page, expect


def _fill_manual_order_form(
    page: Page,
    *,
    tracking: str,
    customer: str = "Jan Testowy E2E",
    price: str = "200",
) -> None:
    page.fill("#customer_name", customer)
    page.fill("#delivery_address", "ul. Testowa 1")
    page.fill("#delivery_city", "Warszawa")
    page.fill("#delivery_postcode", "00-001")
    page.fill("#payment_done", price)
    page.fill("#delivery_package_nr", tracking)

    page.locator('input[name="prod_name[]"]').first.fill("Szelki testowe E2E")
    page.locator('input[name="prod_qty[]"]').first.fill("1")
    page.locator('input[name="prod_price[]"]').first.fill(price)


@pytest.mark.e2e
class TestManualOrderFlow:
    def test_create_manual_olx_order_with_tracking(self, logged_in_page: Page, live_url: str):
        """Formularz add_order z trackingiem ustawia status Wydrukowano."""
        page = logged_in_page
        tracking = "620999681824160672994529"

        page.goto(f"{live_url}/orders/add")
        page.wait_for_load_state("networkidle")
        _fill_manual_order_form(page, tracking=tracking)

        page.get_by_role("button", name="Zapisz zamówienie").click()
        page.wait_for_url("**/order/manual_*")

        expect(page.locator(".badge", has_text="Wydrukowano")).to_be_visible()
        expect(page.get_by_text(tracking)).to_be_visible()
        expect(page.get_by_text("Prowizja platformy")).to_be_visible()
        expect(page.get_by_text("Z formularza")).to_be_visible()
        expect(page.get_by_role("button", name="Drukuj")).to_have_count(0)

    def test_edit_manual_tracking_number(self, logged_in_page: Page, live_url: str):
        """Numer przesylki mozna zmienic w szczegolach zamowienia recznego."""
        page = logged_in_page
        initial_tracking = "TRACK-E2E-INITIAL-001"
        updated_tracking = "TRACK-E2E-UPDATED-002"

        page.goto(f"{live_url}/orders/add")
        page.wait_for_load_state("networkidle")
        _fill_manual_order_form(page, tracking=initial_tracking, customer="Anna Testowa E2E")

        page.get_by_role("button", name="Zapisz zamówienie").click()
        page.wait_for_url("**/order/manual_*")
        expect(page.get_by_text(initial_tracking)).to_be_visible()

        page.fill("#manual_tracking_number", updated_tracking)
        page.get_by_role("button", name="Zapisz").click()
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text(updated_tracking)).to_be_visible()
        expect(page.locator(".badge", has_text="Wydrukowano")).to_be_visible()
