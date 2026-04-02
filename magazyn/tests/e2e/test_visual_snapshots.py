"""Testy wizualne (snapshoty) dla widokow P0.

Uruchamiaj:
    pytest magazyn/tests/e2e/test_visual_snapshots.py --browser chromium

Aktualizacja snapshotow referencyjnych:
    pytest magazyn/tests/e2e/test_visual_snapshots.py --update-snapshots
"""
import pytest
from playwright.sync_api import Page

VIEWPORTS = {
    "mobile": {"width": 360, "height": 800},
    "tablet": {"width": 768, "height": 1024},
    "desktop": {"width": 1280, "height": 900},
}

# JS do zamrazania dynamicznej tresci (daty, timestampy, loading spinnery)
_FREEZE_DYNAMIC_JS = """() => {
    document.querySelectorAll('input[type="date"], input[type="datetime-local"], time, .loading-spinner')
        .forEach(el => el.style.visibility = 'hidden');
    document.querySelectorAll('[data-testid="timestamp"], .relative-time')
        .forEach(el => el.textContent = '---');
}"""

# JS ktory czeka az Alpine skonczy ladowanie (brak spinnerow loading)
_WAIT_ALPINE_IDLE_JS = """() => {
    const spinners = document.querySelectorAll('.loading-spinner:not([style*="display: none"])');
    for (const s of spinners) {
        if (s.offsetParent !== null) return false;
    }
    return true;
}"""

# JS do wymuszenia zaladowania wszystkich leniwych sekcji Stats (IntersectionObserver)
# i oczekiwania az wszystkie flagi *Loading beda false
_STATS_WAIT_ALL_LOADED_JS = """() => {
    const shell = document.querySelector('.stats-shell');
    if (!shell || typeof Alpine === 'undefined') return true;
    try {
        const d = Alpine.$data(shell);
        if (!d) return true;
        const flags = [
            'loading', 'returnsLoading', 'logisticsLoading', 'productsLoading',
            'competitionLoading', 'orderFunnelLoading', 'shipmentErrorsLoading',
            'customerSupportLoading', 'invoiceCoverageLoading', 'adsOfferAnalyticsLoading',
            'refundTimelineLoading', 'offerPublicationHistoryLoading', 'billingTypesLoading'
        ];
        return flags.every(f => d[f] === false || d[f] === undefined);
    } catch(e) { return true; }
}"""

_STATS_FORCE_LOAD_JS = """async () => {
    const shell = document.querySelector('.stats-shell');
    if (!shell || typeof Alpine === 'undefined') return;
    const d = Alpine.$data(shell);
    if (!d) return;

    // Wymusza zaladowanie sekcji lazy, ktore normalnie czekaja na scroll.
    const loaders = [
        'loadReturns', 'loadLogistics', 'loadProducts', 'loadCompetition',
        'loadOrderFunnel', 'loadShipmentErrors', 'loadCustomerSupport',
        'loadInvoiceCoverage', 'loadAdsOfferAnalytics', 'loadRefundTimeline',
        'loadOfferPublicationHistory', 'loadBillingTypes'
    ];
    const pending = [];
    for (const name of loaders) {
        if (typeof d[name] === 'function') {
            try {
                pending.push(d[name]());
            } catch (e) {
                // Ignorujemy pojedyncze bledy loaderow, test i tak sprawdzi finalny screenshot.
            }
        }
    }
    await Promise.allSettled(pending);
}"""


def _goto_and_stabilize(page: Page, url: str, vp: dict):
    """Nawiguje, stabilizuje strone i zamraza dynamiczne elementy."""
    page.set_viewport_size(vp)
    page.goto(url)
    page.wait_for_load_state("networkidle")
    # Czekamy az znikna wszelkie loading-spinnery (Alpine async sections)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.loading-spinner').length === 0 "
            "|| [...document.querySelectorAll('.loading-spinner')].every(s => s.offsetParent === null)",
            timeout=10000,
        )
    except Exception:
        pass
    # Dodatkowy networkidle po zaladowaniu danych
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    page.evaluate(_FREEZE_DYNAMIC_JS)


def _goto_and_stabilize_stats(page: Page, url: str, vp: dict):
    """Specjalna stabilizacja dla dashboardu Stats z lazy-loaded sekcjami."""
    page.set_viewport_size(vp)
    page.goto(url)
    page.wait_for_load_state("networkidle")

    # Najpierw wymuszenie loaderow bez zaleznosci od IntersectionObserver.
    page.evaluate(_STATS_FORCE_LOAD_JS)
    page.wait_for_load_state("networkidle")

    # Przewin calkowita strone do dolu zeby IntersectionObserver wyzwolil lazy sekcje
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    # Przewin jeszcze dalej (po zaladowaniu nowych elementow strona moze byc dluzsza)
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    # Powrot na gore
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(300)

    # Czekaj na zakonczenie wszystkich fetchow Alpine (flagi *Loading === false)
    try:
        page.wait_for_function(_STATS_WAIT_ALL_LOADED_JS, timeout=15000)
    except Exception:
        pass

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.evaluate(_FREEZE_DYNAMIC_JS)


class TestHomePage:
    """Snapshoty strony glownej (home)."""

    @pytest.mark.parametrize("viewport_name", ["mobile", "tablet", "desktop"])
    def test_home_no_overflow(self, logged_in_page: Page, live_url: str, viewport_name: str):
        vp = VIEWPORTS[viewport_name]
        logged_in_page.set_viewport_size(vp)
        logged_in_page.goto(f"{live_url}/")
        logged_in_page.wait_for_load_state("networkidle")

        overflow = logged_in_page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, (
            f"Strona glowna ma poziomy overflow na {viewport_name} "
            f"({vp['width']}x{vp['height']})"
        )

    @pytest.mark.parametrize("viewport_name", ["mobile", "tablet", "desktop"])
    def test_home_snapshot(self, logged_in_page: Page, live_url: str, viewport_name: str, assert_snapshot):
        _goto_and_stabilize(logged_in_page, f"{live_url}/", VIEWPORTS[viewport_name])
        assert_snapshot(
            logged_in_page.screenshot(full_page=True),
            f"home-{viewport_name}.png",
        )


class TestStatsDashboard:
    """Snapshoty dashboardu statystyk."""

    @pytest.mark.parametrize("viewport_name", ["mobile", "tablet", "desktop"])
    def test_stats_no_overflow(self, logged_in_page: Page, live_url: str, viewport_name: str):
        vp = VIEWPORTS[viewport_name]
        logged_in_page.set_viewport_size(vp)
        logged_in_page.goto(f"{live_url}/stats")
        logged_in_page.wait_for_load_state("networkidle")

        overflow = logged_in_page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, (
            f"Dashboard statystyk ma poziomy overflow na {viewport_name} "
            f"({vp['width']}x{vp['height']})"
        )

    @pytest.mark.parametrize("viewport_name", ["mobile", "tablet", "desktop"])
    def test_stats_snapshot(self, logged_in_page: Page, live_url: str, viewport_name: str, assert_snapshot):
        _goto_and_stabilize_stats(logged_in_page, f"{live_url}/stats", VIEWPORTS[viewport_name])
        assert_snapshot(
            logged_in_page.screenshot(full_page=False),
            f"stats-{viewport_name}.png",
        )


class TestOrdersList:
    """Snapshoty listy zamowien."""

    @pytest.mark.parametrize("viewport_name", ["mobile", "tablet", "desktop"])
    def test_orders_no_overflow(self, logged_in_page: Page, live_url: str, viewport_name: str):
        vp = VIEWPORTS[viewport_name]
        logged_in_page.set_viewport_size(vp)
        logged_in_page.goto(f"{live_url}/orders")
        logged_in_page.wait_for_load_state("networkidle")

        overflow = logged_in_page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, (
            f"Lista zamowien ma poziomy overflow na {viewport_name} "
            f"({vp['width']}x{vp['height']})"
        )

    @pytest.mark.parametrize("viewport_name", ["mobile", "tablet", "desktop"])
    def test_orders_snapshot(self, logged_in_page: Page, live_url: str, viewport_name: str, assert_snapshot):
        _goto_and_stabilize(logged_in_page, f"{live_url}/orders", VIEWPORTS[viewport_name])
        assert_snapshot(
            logged_in_page.screenshot(full_page=True),
            f"orders-{viewport_name}.png",
        )


class TestItems:
    """Snapshoty listy przedmiotow."""

    @pytest.mark.parametrize("viewport_name", ["mobile", "tablet", "desktop"])
    def test_items_no_overflow(self, logged_in_page: Page, live_url: str, viewport_name: str):
        vp = VIEWPORTS[viewport_name]
        logged_in_page.set_viewport_size(vp)
        logged_in_page.goto(f"{live_url}/items")
        logged_in_page.wait_for_load_state("networkidle")

        overflow = logged_in_page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, (
            f"Lista przedmiotow ma poziomy overflow na {viewport_name} "
            f"({vp['width']}x{vp['height']})"
        )

    @pytest.mark.parametrize("viewport_name", ["mobile", "tablet", "desktop"])
    def test_items_snapshot(self, logged_in_page: Page, live_url: str, viewport_name: str, assert_snapshot):
        _goto_and_stabilize(logged_in_page, f"{live_url}/items", VIEWPORTS[viewport_name])
        assert_snapshot(
            logged_in_page.screenshot(full_page=True),
            f"items-{viewport_name}.png",
        )