import time
from datetime import datetime, timedelta

from magazyn.db import get_session
from magazyn.models import Order, OrderProduct


def _seed_orders(app, count: int = 200):
    now_ts = int(datetime.now().timestamp())
    with app.app_context():
        with get_session() as db:
            for i in range(count):
                order_id = f"perf_ord_{i}"
                cod = (i % 4) == 0
                order = Order(
                    order_id=order_id,
                    platform="allegro" if i % 2 == 0 else "shop",
                    date_add=now_ts - (i % 20) * 86400,
                    payment_done=120.0 if not cod else 0.0,
                    payment_method_cod=cod,
                    payment_method="Pobranie" if cod else "Przelew online",
                    delivery_price=15.0 if cod else 0.0,
                    currency="PLN",
                )
                db.add(order)
                db.flush()
                db.add(
                    OrderProduct(
                        order_id=order_id,
                        name="Produkt testowy",
                        ean=f"ean-{i % 15}",
                        quantity=(i % 3) + 1,
                        price_brutto=40.0 + (i % 10),
                    )
                )


def test_stats_endpoints_performance_budget(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    stats_module._TELEMETRY.clear()
    _seed_orders(app, 220)

    endpoints = [
        "/api/stats/overview",
        "/api/stats/sales",
        "/api/stats/profit",
        "/api/stats/returns",
        "/api/stats/logistics",
        "/api/stats/products",
        "/api/stats/competition",
    ]

    timings = {}
    for endpoint in endpoints:
        start = time.perf_counter()
        response = client.get(endpoint)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert response.status_code == 200
        timings[endpoint] = elapsed_ms

    # Luzny budzet dla srodowiska testowego sqlite i bez warmup
    assert max(timings.values()) < 2500


def test_stats_dashboard_page_renders(client, login):
    response = client.get("/stats")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Centrum Statystyk" in html
    assert "Sekcja załaduje się po przewinięciu" in html
