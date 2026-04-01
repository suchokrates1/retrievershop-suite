from datetime import datetime, timedelta
from types import SimpleNamespace

from magazyn.db import get_session
from magazyn.models import AllegroPriceHistory, Order, OrderProduct, OrderStatusLog, PriceReport, PriceReportItem, Return


def _seed_order(app, order_id: str, *, payment_done=100.0, cod=False, platform="allegro"):
    now_ts = int(datetime.now().timestamp())
    with app.app_context():
        with get_session() as db:
            order = Order(
                order_id=order_id,
                platform=platform,
                date_add=now_ts,
                payment_done=payment_done,
                payment_method_cod=cod,
                payment_method="Pobranie" if cod else "Przelew online",
                delivery_price=15.57 if cod else 0,
                currency="PLN",
            )
            db.add(order)
            db.flush()
            db.add(
                OrderProduct(
                    order_id=order_id,
                    name="Test produkt",
                    quantity=2,
                    price_brutto=50.00,
                )
            )


def _seed_return(app, order_id: str, *, status="pending", refund_processed=False, stock_restored=False):
    with app.app_context():
        with get_session() as db:
            db.add(
                Return(
                    order_id=order_id,
                    status=status,
                    refund_processed=refund_processed,
                    stock_restored=stock_restored,
                )
            )


def _seed_status_log(app, order_id: str, status: str, dt: datetime):
    with app.app_context():
        with get_session() as db:
            db.add(
                OrderStatusLog(
                    order_id=order_id,
                    status=status,
                    timestamp=dt,
                )
            )


def _seed_competition_data(app, offer_id: str):
    now = datetime.now()
    with app.app_context():
        with get_session() as db:
            report = PriceReport(status="completed", items_total=1, items_checked=1)
            db.add(report)
            db.flush()
            db.add(
                PriceReportItem(
                    report_id=report.id,
                    offer_id=offer_id,
                    our_price=120.0,
                    competitor_price=100.0,
                    our_position=2,
                    checked_at=now,
                )
            )
            db.add(
                AllegroPriceHistory(
                    offer_id=offer_id,
                    price=118.0,
                    competitor_price=101.0,
                    recorded_at=now.strftime("%Y-%m-%d"),
                )
            )


def test_stats_overview_returns_payload(client, app, login):
    _seed_order(app, "ord_stats_1", payment_done=100.0, cod=False)

    response = client.get("/api/stats/overview")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    assert "data" in payload
    assert "kpi" in payload["data"]
    assert "revenue_gross" in payload["data"]["kpi"]


def test_stats_overview_validates_granularity(client, login):
    response = client.get("/api/stats/overview?granularity=year")
    assert response.status_code == 400

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "INVALID_GRANULARITY"


def test_stats_overview_handles_cod_revenue(client, app, login):
    _seed_order(app, "ord_stats_cod", payment_done=0.0, cod=True)

    response = client.get("/api/stats/overview?payment_type=cod")
    assert response.status_code == 200

    payload = response.get_json()
    revenue = payload["data"]["kpi"]["revenue_gross"]["value"]
    # 2 * 50 + 15.57 (dostawa) = 115.57
    assert round(float(revenue), 2) == 115.57


def test_stats_overview_cache_hit(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    _seed_order(app, "ord_stats_cache", payment_done=120.0, cod=False)

    first = client.get("/api/stats/overview")
    assert first.status_code == 200
    first_payload = first.get_json()
    assert first_payload["meta"]["cache"] == "miss"

    second = client.get("/api/stats/overview")
    assert second.status_code == 200
    second_payload = second.get_json()
    assert second_payload["meta"]["cache"] == "hit"


def test_stats_sales_returns_series_and_summary(client, app, login):
    _seed_order(app, "ord_sales_1", payment_done=100.0, cod=False, platform="allegro")
    _seed_order(app, "ord_sales_2", payment_done=0.0, cod=True, platform="shop")

    response = client.get("/api/stats/sales?granularity=day")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    assert isinstance(payload["data"]["series"], list)
    assert "summary" in payload["data"]
    assert "mom" in payload["data"]["summary"]


def test_stats_profit_returns_summary(client, app, login, monkeypatch):
    from magazyn import stats as stats_module

    class _FakeCalculator:
        def __init__(self, db, settings):
            self.db = db
            self.settings = settings

        def get_period_summary(self, start_ts, end_ts, include_fixed_costs=True, access_token=None):
            return SimpleNamespace(
                total_revenue=200.0,
                total_purchase_cost=80.0,
                total_allegro_fees=20.0,
                total_packaging_cost=10.0,
                fixed_costs=15.0,
                net_profit=75.0,
                gross_profit=90.0,
            )

    monkeypatch.setattr(stats_module, "FinancialCalculator", _FakeCalculator)
    monkeypatch.setattr(stats_module.settings_store, "get", lambda key, default=None: "token" if key == "ALLEGRO_ACCESS_TOKEN" else default)

    response = client.get("/api/stats/profit")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["summary"]["net_profit"] == 75.0
    assert len(payload["data"]["waterfall"]) >= 5


def test_stats_allegro_costs_returns_totals(client, app, login, monkeypatch):
    from magazyn import allegro_api as allegro_api_module
    from magazyn import stats as stats_module

    _seed_order(app, "ord_cost_1", payment_done=100.0, cod=False)

    monkeypatch.setattr(stats_module.settings_store, "get", lambda key, default=None: "token" if key == "ALLEGRO_ACCESS_TOKEN" else default)
    monkeypatch.setattr(
        allegro_api_module,
        "fetch_billing_entries",
        lambda token, occurred_at_gte=None, occurred_at_lte=None, limit=100: {
            "billingEntries": [
                {"type": {"id": "FEE1"}, "value": {"amount": "-12.34"}},
                {"type": {"id": "FEE2"}, "value": {"amount": "-3.66"}},
            ]
        },
    )
    monkeypatch.setattr(
        allegro_api_module,
        "fetch_billing_types",
        lambda token: [
            {"id": "FEE1", "name": "Prowizja"},
            {"id": "FEE2", "name": "Wyroznienie"},
        ],
    )
    monkeypatch.setattr(
        allegro_api_module,
        "get_period_ads_cost",
        lambda token, date_from, date_to: {
            "total_cost": 7.0,
            "daily_costs": [{"date": "2025-01-01", "cost": 7.0}],
        },
    )

    response = client.get("/api/stats/allegro-costs")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["totals"]["allegro_total"] == 16.0
    assert payload["data"]["totals"]["ads_total"] == 7.0


def test_stats_allegro_costs_requires_token(client, login, monkeypatch):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    monkeypatch.setattr(stats_module.settings_store, "get", lambda key, default=None: default)

    response = client.get("/api/stats/allegro-costs")
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "ALLEGRO_TOKEN_MISSING"


def test_stats_returns_summary_and_refund_metrics(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    _seed_order(app, "ord_ret_1", payment_done=120.0)
    _seed_order(app, "ord_ret_2", payment_done=80.0)
    _seed_return(app, "ord_ret_1", status="completed", refund_processed=True, stock_restored=True)
    _seed_return(app, "ord_ret_2", status="in_transit", refund_processed=False, stock_restored=False)

    response = client.get("/api/stats/returns")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["ok"] is True
    assert payload["data"]["summary"]["returns_total"] == 2
    assert payload["data"]["summary"]["refund_processed"] == 1
    assert payload["data"]["status_breakdown"]["completed"] == 1


def test_stats_logistics_returns_lead_time(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    _seed_order(app, "ord_log_1", payment_done=150.0)

    now = datetime.now()
    with app.app_context():
        with get_session() as db:
            order = db.query(Order).filter(Order.order_id == "ord_log_1").first()
            order.delivery_package_nr = "TRK123"

    _seed_status_log(app, "ord_log_1", "spakowano", now)
    _seed_status_log(app, "ord_log_1", "dostarczono", now + timedelta(hours=2))

    response = client.get("/api/stats/logistics")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["ok"] is True
    assert payload["data"]["summary"]["shipped_total"] == 1
    assert payload["data"]["summary"]["delivered_total"] == 1
    assert "avg_lead_time_hours" in payload["data"]["summary"]


def test_stats_products_returns_rows_with_recommendation(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    _seed_order(app, "ord_prod_1", payment_done=100.0, cod=False)
    _seed_order(app, "ord_prod_2", payment_done=0.0, cod=True)

    response = client.get("/api/stats/products")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["ok"] is True
    assert len(payload["data"]["rows"]) >= 1
    assert "repricing_recommendation" in payload["data"]["rows"][0]


def test_stats_competition_merges_report_and_history(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    _seed_competition_data(app, "offer-test-1")

    response = client.get("/api/stats/competition")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["ok"] is True
    assert len(payload["data"]["rows"]) == 1
    row = payload["data"]["rows"][0]
    assert row["offer_id"] == "offer-test-1"
    assert row["our_history_price"] == 118.0
    assert row["repricing_recommendation"] == "decrease_3pct"


def test_stats_products_export_csv(client, app, login):
    _seed_order(app, "ord_prod_csv", payment_done=100.0, cod=False)

    response = client.get("/api/stats/products?format=csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert b"repricing_recommendation" in response.data


def test_stats_competition_export_xlsx(client, app, login):
    _seed_competition_data(app, "offer-test-xlsx")

    response = client.get("/api/stats/competition?format=xlsx")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(response.data) > 50


def test_stats_telemetry_collects_cache_and_response_time(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    stats_module._TELEMETRY.clear()
    _seed_order(app, "ord_tel_1", payment_done=100.0, cod=False)

    first = client.get("/api/stats/overview")
    assert first.status_code == 200
    first_payload = first.get_json()
    assert "telemetry" in first_payload["meta"]

    second = client.get("/api/stats/overview")
    assert second.status_code == 200

    tele = client.get("/api/stats/telemetry")
    assert tele.status_code == 200
    data = tele.get_json()["data"]
    assert "overview" in data
    assert data["overview"]["requests"] >= 2
    assert data["overview"]["cache_hits"] >= 1

# ---- Sprint 6 ---------------------------------------------------------------


def test_stats_overview_mom_structure(client, app, login):
    """MoM/WoW musi miec klucze (wartosc moze byc None gdy brak danych historycznych)."""
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    _seed_order(app, "ord_s6_str", payment_done=200.0)

    response = client.get("/api/stats/overview")
    assert response.status_code == 200
    kpi = response.get_json()["data"]["kpi"]

    for metric_name in ("revenue_gross", "orders_count", "items_sold", "aov", "returns_rate", "cod_share"):
        assert metric_name in kpi, f"brak klucza {metric_name}"
        assert "mom" in kpi[metric_name], f"brak klucza mom w {metric_name}"


def test_stats_overview_mom_not_none_with_historical_data(client, app, login):
    """Gdy istnieja zamowienia w poprzednim odcinku (50 dni temu) MoM powinno byc liczba.

    Zakres zapytania: date_from=45 dni temu, date_to=dzisiaj (45-dniowy period).
    Poprzedni odcinek wyliczany przez _period_offsets: [90 dni temu, 45 dni temu].
    Zamowienie 50 dni temu trafi do poprzedniego odcinka => prv_revenue > 0 => MoM != None.
    """
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()

    today = datetime.now()
    # Zamowienie w poprzednim okresie: 50 dni temu (trafi do okna 90-45 dni temu)
    past_ts = int((today - timedelta(days=50)).timestamp())

    with app.app_context():
        with get_session() as db:
            order = Order(
                order_id="ord_s6_hist",
                platform="allegro",
                date_add=past_ts,
                payment_done=150.0,
                payment_method_cod=False,
                payment_method="Przelew online",
                delivery_price=0,
                currency="PLN",
            )
            db.add(order)
            db.flush()
            db.add(OrderProduct(order_id="ord_s6_hist", name="Prod hist", quantity=1, price_brutto=150.0))

    # Zamowienie w biezacym okresie: dzisiaj
    _seed_order(app, "ord_s6_cur2", payment_done=200.0)

    # Zakres 45 dni: poprzedni odcinek to [90 dni temu, 45 dni temu]
    date_from = (today - timedelta(days=45)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")
    resp = client.get(f"/api/stats/overview?date_from={date_from}&date_to={date_to}")
    assert resp.status_code == 200
    kpi = resp.get_json()["data"]["kpi"]
    assert kpi["revenue_gross"]["value"] > 0
    assert "mom" in kpi["revenue_gross"]
    # Przy danych w poprzednim odcinku MoM musi byc obliczone (nie None)
    assert kpi["revenue_gross"]["mom"] is not None


def test_stats_logistics_funnel_and_error_counts(client, app, login):
    """Logistics zwraca funnel i error_counts."""
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    _seed_order(app, "ord_s6_log", payment_done=100.0)

    now = datetime.now()
    _seed_status_log(app, "ord_s6_log", "wydrukowano", now)
    _seed_status_log(app, "ord_s6_log", "spakowano", now + timedelta(minutes=10))
    _seed_status_log(app, "ord_s6_log", "wyslano", now + timedelta(hours=1))
    _seed_status_log(app, "ord_s6_log", "blad_druku", now + timedelta(minutes=5))

    response = client.get("/api/stats/logistics")
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert "funnel" in data
    funnel_statuses = [s["status"] for s in data["funnel"]]
    assert "wydrukowano" in funnel_statuses
    assert "spakowano" in funnel_statuses

    assert "error_counts" in data
    assert data["error_counts"]["blad_druku"] == 1
    assert "zwrot" in data["error_counts"]


def test_stats_profit_waterfall_structure(client, app, login, monkeypatch):
    """Profit zwraca waterfall z Przychodem i Zyskiem netto."""
    from magazyn import stats as stats_module
    from magazyn.domain.financial import FinancialCalculator

    stats_module._FAST_CACHE.clear()
    _seed_order(app, "ord_s6_wf", payment_done=500.0)

    fake_summary = SimpleNamespace(
        total_revenue=500.0,
        total_purchase_cost=200.0,
        total_allegro_fees=50.0,
        total_packaging_cost=10.0,
        fixed_costs=30.0,
        ads_cost=0.0,
        gross_profit=240.0,
        net_profit=210.0,
    )
    monkeypatch.setattr(FinancialCalculator, "get_period_summary", lambda *a, **kw: fake_summary)

    response = client.get("/api/stats/profit")
    assert response.status_code == 200
    payload = response.get_json()

    assert "waterfall" in payload["data"]
    names = [w["name"] for w in payload["data"]["waterfall"]]
    assert "Przychod" in names
    assert "Zysk netto" in names
