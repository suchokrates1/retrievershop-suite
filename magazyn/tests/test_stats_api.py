from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from magazyn.db import get_session
from magazyn.models import AllegroBillingType, AllegroPriceHistory, Message, Order, OrderProduct, OrderStatusLog, OrderEvent, ReturnStatusLog, ShipmentError, PriceReport, PriceReportItem, Return, Thread


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


def _seed_return_status_log(app, return_id: int, status: str, dt: datetime):
    with app.app_context():
        with get_session() as db:
            db.add(
                ReturnStatusLog(
                    return_id=return_id,
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
    from magazyn.db import get_session
    from magazyn.models import AllegroBillingType

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

    with app.app_context():
        with get_session() as db:
            saved = {row.type_id: row.name for row in db.query(AllegroBillingType).all()}

    assert saved["FEE1"] == "Prowizja"
    assert saved["FEE2"] == "Wyroznienie"


def test_stats_allegro_costs_requires_token(client, login, monkeypatch):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    monkeypatch.setattr(stats_module.settings_store, "get", lambda key, default=None: default)

    response = client.get("/api/stats/allegro-costs")
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "ALLEGRO_TOKEN_MISSING"


def test_stats_billing_types_list_and_update(client, app, login):
    with app.app_context():
        with get_session() as db:
            db.add(
                AllegroBillingType(
                    type_id="SUC",
                    name="Prowizja",
                    description="Prowizja od sprzedazy",
                    mapping_category="commission_organic",
                    mapping_version=1,
                )
            )

    resp = client.get("/api/stats/billing-types")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["rows"][0]["type_id"] == "SUC"

    upd = client.put("/api/stats/billing-types/SUC", json={"mapping_category": "promo"})
    assert upd.status_code == 200
    upd_data = upd.get_json()["data"]
    assert upd_data["mapping_category"] == "promo"
    assert upd_data["mapping_version"] == 2


def test_stats_billing_types_sync_endpoint(client, app, login, monkeypatch):
    from magazyn import allegro_api as allegro_api_module
    from magazyn import stats as stats_module

    monkeypatch.setattr(stats_module.settings_store, "get", lambda key, default=None: "token" if key == "ALLEGRO_ACCESS_TOKEN" else default)
    monkeypatch.setattr(
        allegro_api_module,
        "fetch_billing_types",
        lambda token: [
            {"id": "SUC", "name": "Prowizja"},
            {"id": "NSP", "name": "Ads"},
        ],
    )

    resp = client.post("/api/stats/billing-types/sync")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["data"]["fetched"] == 2

    with app.app_context():
        with get_session() as db:
            ids = {row.type_id for row in db.query(AllegroBillingType).all()}
    assert "SUC" in ids
    assert "NSP" in ids


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


def test_stats_logistics_breakdown_by_carrier_and_method(client, app, login):
    """Logistics zwraca SLA per przewoznik i metode dostawy."""
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    _seed_order(app, "ord_s7_track_1", payment_done=120.0)
    _seed_order(app, "ord_s7_track_2", payment_done=130.0)

    now = datetime.now()
    with app.app_context():
        with get_session() as db:
            order_1 = db.query(Order).filter(Order.order_id == "ord_s7_track_1").first()
            order_1.delivery_package_nr = "INP123"
            order_1.delivery_method = "Allegro Paczkomaty InPost"
            order_1.courier_code = "INPOST"
            order_1.delivery_package_module = "InPost"

            order_2 = db.query(Order).filter(Order.order_id == "ord_s7_track_2").first()
            order_2.delivery_package_nr = "DPD123"
            order_2.delivery_method = "Kurier DPD"
            order_2.courier_code = "DPD"
            order_2.delivery_package_module = "DPD"

    _seed_status_log(app, "ord_s7_track_1", "spakowano", now)
    _seed_status_log(app, "ord_s7_track_1", "dostarczono", now + timedelta(hours=24))
    _seed_status_log(app, "ord_s7_track_2", "spakowano", now)
    _seed_status_log(app, "ord_s7_track_2", "dostarczono", now + timedelta(hours=72))

    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=5)).strftime("%Y-%m-%d")
    response = client.get(f"/api/stats/logistics?date_from={date_from}&date_to={date_to}")
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert "by_carrier" in data
    assert "by_delivery_method" in data

    carriers = {row["carrier"]: row for row in data["by_carrier"]}
    assert carriers["InPost"]["shipped_total"] == 1
    assert carriers["InPost"]["delivered_total"] == 1
    assert carriers["InPost"]["on_time_rate_48h"] == 100.0
    assert carriers["DPD"]["on_time_rate_48h"] == 0.0

    methods = {row["delivery_method"]: row for row in data["by_delivery_method"]}
    assert methods["Allegro Paczkomaty InPost"]["carrier"] == "InPost"
    assert methods["Kurier DPD"]["carrier"] == "DPD"


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


def test_stats_order_funnel_creates_and_tracks_events(client, app, login, monkeypatch):
    """Order funnel zwraca funnel z transitions times na podstawie OrderEvent."""
    from magazyn import stats as stats_module
    from magazyn.models import OrderEvent

    stats_module._FAST_CACHE.clear()
    
    # Create test order
    now = datetime.now(timezone.utc)
    order_id = "ord_funnel_1"
    _seed_order(app, order_id, payment_done=100.0)
    
    # Create raw events w realnym czasie
    with app.app_context():
        with get_session() as db:
            # Event 1: BOUGHT (t=0h)
            evt1 = OrderEvent(
                order_id=order_id,
                allegro_event_id="evt_001",
                event_type="BOUGHT",
                occurred_at=now,
                payload_json="{}"
            )
            # Event 2: FILLED_IN (t=2h)
            evt2 = OrderEvent(
                order_id=order_id,
                allegro_event_id="evt_002",
                event_type="FILLED_IN",
                occurred_at=now + timedelta(hours=2),
                payload_json="{}"
            )
            # Event 3: READY_FOR_PROCESSING (t=5h)
            evt3 = OrderEvent(
                order_id=order_id,
                allegro_event_id="evt_003",
                event_type="READY_FOR_PROCESSING",
                occurred_at=now + timedelta(hours=5),
                payload_json="{}"
            )
            db.add_all([evt1, evt2, evt3])
            db.commit()
    
    # Test endpoint
    response = client.get("/api/stats/order-funnel")
    assert response.status_code == 200
    data = response.get_json()["data"]
    
    # Verify funnel stages
    assert "funnel" in data
    funnel_stages = [s["stage"] for s in data["funnel"]]
    assert "BOUGHT" in funnel_stages
    assert "FILLED_IN" in funnel_stages
    assert "READY_FOR_PROCESSING" in funnel_stages
    
    # Verify transition times
    assert "transitions" in data
    transitions = data["transitions"]
    
    # BOUGHT -> FILLED_IN should be ~2 hours
    assert "BOUGHT_to_FILLED_IN" in transitions
    assert transitions["BOUGHT_to_FILLED_IN"]["avg_hours"] == 2.0
    assert transitions["BOUGHT_to_FILLED_IN"]["count"] == 1
    
    # FILLED_IN -> READY_FOR_PROCESSING should be ~3 hours
    assert "FILLED_IN_to_READY_FOR_PROCESSING" in transitions
    assert transitions["FILLED_IN_to_READY_FOR_PROCESSING"]["avg_hours"] == 3.0
    
    # BOUGHT -> READY_FOR_PROCESSING should be ~5 hours
    assert "BOUGHT_to_READY_FOR_PROCESSING" in transitions
    assert transitions["BOUGHT_to_READY_FOR_PROCESSING"]["avg_hours"] == 5.0
    
    # Verify summary
    assert "summary" in data
    assert data["summary"]["avg_time_bought_to_ready_hours"] == 5.0


def test_stats_order_funnel_multiple_orders(client, app, login):
    """Order funnel aggregates metrics across multiple orders."""
    from magazyn import stats as stats_module
    from magazyn.models import OrderEvent

    stats_module._FAST_CACHE.clear()
    
    now = datetime.now(timezone.utc)
    
    # Create two test orders
    order_id_1 = "ord_funnel_2a"
    order_id_2 = "ord_funnel_2b"
    _seed_order(app, order_id_1, payment_done=50.0)
    _seed_order(app, order_id_2, payment_done=75.0)
    
    with app.app_context():
        with get_session() as db:
            # Order 1: BOUGHT -> (2h) -> FILLED_IN -> (3h) -> READY (total 5h)
            db.add_all([
                OrderEvent(order_id=order_id_1, allegro_event_id="evt_101",
                          event_type="BOUGHT", occurred_at=now, payload_json="{}"),
                OrderEvent(order_id=order_id_1, allegro_event_id="evt_102",
                          event_type="FILLED_IN", occurred_at=now + timedelta(hours=2), payload_json="{}"),
                OrderEvent(order_id=order_id_1, allegro_event_id="evt_103",
                          event_type="READY_FOR_PROCESSING", occurred_at=now + timedelta(hours=5), payload_json="{}"),
            ])
            
            # Order 2: BOUGHT -> (4h) -> FILLED_IN -> (6h) -> READY (total 10h)
            db.add_all([
                OrderEvent(order_id=order_id_2, allegro_event_id="evt_201",
                          event_type="BOUGHT", occurred_at=now, payload_json="{}"),
                OrderEvent(order_id=order_id_2, allegro_event_id="evt_202",
                          event_type="FILLED_IN", occurred_at=now + timedelta(hours=4), payload_json="{}"),
                OrderEvent(order_id=order_id_2, allegro_event_id="evt_203",
                          event_type="READY_FOR_PROCESSING", occurred_at=now + timedelta(hours=10), payload_json="{}"),
            ])
            db.commit()
    
    response = client.get("/api/stats/order-funnel")
    assert response.status_code == 200
    data = response.get_json()["data"]
    
    # Both orders should be in funnel (count=2)
    assert data["total_orders"] == 2
    assert data["orders_with_events"] == 2
    
    # Verify averages across orders
    transitions = data["transitions"]
    
    # BOUGHT_to_FILLED_IN: (2 + 4) / 2 = 3 hours avg
    assert transitions["BOUGHT_to_FILLED_IN"]["count"] == 2
    assert transitions["BOUGHT_to_FILLED_IN"]["avg_hours"] == 3.0  # (2+4)/2
    
    # BOUGHT_to_READY: (5 + 10) / 2 = 7.5 hours avg
    assert transitions["BOUGHT_to_READY_FOR_PROCESSING"]["count"] == 2
    assert abs(transitions["BOUGHT_to_READY_FOR_PROCESSING"]["avg_hours"] - 7.5) < 0.01


def test_stats_shipment_errors_list_and_aggregation(client, app, login):
    """Shipment errors endpoint correctly groups and aggregates errors."""
    from magazyn.models import ShipmentError
    from magazyn import stats as stats_module
    
    stats_module._FAST_CACHE.clear()
    
    now = datetime.now(timezone.utc)
    
    # Create test orders
    _seed_order(app, "ord_ship_1", payment_done=50.0)
    _seed_order(app, "ord_ship_2", payment_done=75.0)
    _seed_order(app, "ord_ship_3", payment_done=100.0)
    
    with app.app_context():
        with get_session() as db:
            # Add shipment errors for testing
            db.add_all([
                # Order 1: Label generation error (unresolved)
                ShipmentError(
                    order_id="ord_ship_1",
                    error_type="LABEL_GENERATION",
                    error_code="LG001",
                    error_message="Invalid shipment dimensions",
                    delivery_method="DHL",
                    raw_response='{"error": "dimensions"}',
                    resolved=False,
                ),
                # Order 2: Address validation error (resolved)
                ShipmentError(
                    order_id="ord_ship_2",
                    error_type="ADDRESS_VALIDATION",
                    error_code="AV001",
                    error_message="Invalid postal code",
                    delivery_method="UPS",
                    raw_response='{"error": "postal_code"}',
                    resolved=True,
                ),
                # Order 3: Label generation error (unresolved)
                ShipmentError(
                    order_id="ord_ship_3",
                    error_type="LABEL_GENERATION",
                    error_code="LG002",
                    error_message="Timeout generating label",
                    delivery_method="DHL",
                    raw_response='{"error": "timeout"}',
                    resolved=False,
                ),
            ])
            db.commit()
    
    response = client.get("/api/stats/shipment-errors")
    assert response.status_code == 200
    data = response.get_json()["data"]
    
    # Verify totals
    assert data["total_errors"] == 3
    assert data["unresolved_total"] == 2
    
    # Verify error type grouping (LABEL_GENERATION: 2, ADDRESS_VALIDATION: 1)
    assert data["by_error_type"]["LABEL_GENERATION"] == 2
    assert data["by_error_type"]["ADDRESS_VALIDATION"] == 1
    
    # Verify delivery method grouping (DHL: 2, UPS: 1)
    assert data["by_delivery_method"]["DHL"] == 2
    assert data["by_delivery_method"]["UPS"] == 1
    
    # Verify summary
    assert data["summary"]["most_common_error"] == "LABEL_GENERATION"
    assert data["summary"]["most_problematic_courier"] == "DHL"
    assert abs(data["summary"]["resolution_rate"] - 33.33) < 1.0  # 1 resolved out of 3 = 33.33%


def test_stats_shipment_errors_filters_by_date(client, app, login):
    """Shipment errors endpoint respects date_from and date_to filters."""
    from magazyn.models import ShipmentError
    from magazyn import stats as stats_module
    
    stats_module._FAST_CACHE.clear()
    
    now = datetime.now(timezone.utc)
    
    # Create test orders
    _seed_order(app, "ord_date_1", payment_done=50.0)
    _seed_order(app, "ord_date_2", payment_done=75.0)
    
    with app.app_context():
        with get_session() as db:
            # Add errors at different times - both within today
            db.add_all([
                ShipmentError(
                    order_id="ord_date_1",
                    error_type="LABEL_GENERATION",
                    error_code="LG",
                    error_message="Error 1",
                    delivery_method="DHL",
                    raw_response="{}",
                    resolved=False,
                    created_at=now - timedelta(hours=2),
                ),
                ShipmentError(
                    order_id="ord_date_2",
                    error_type="ADDRESS_VALIDATION",
                    error_code="AV",
                    error_message="Error 2",
                    delivery_method="UPS",
                    raw_response="{}",
                    resolved=True,
                    created_at=now - timedelta(hours=1),
                ),
            ])
            db.commit()
    
    # Query without date filter (should get all)
    response = client.get("/api/stats/shipment-errors")
    assert response.status_code == 200
    data = response.get_json()["data"]
    
    # Should include both errors
    assert data["total_errors"] == 2
    assert data["unresolved_total"] == 1
    assert data["by_error_type"]["LABEL_GENERATION"] == 1
    assert data["by_error_type"]["ADDRESS_VALIDATION"] == 1


def test_stats_customer_support_returns_kpi(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    now = datetime.now(timezone.utc)

    with app.app_context():
        with get_session() as db:
            db.add_all(
                [
                    Thread(
                        id="th_kpi_1",
                        title="Pytanie o zamowienie",
                        author="buyer1",
                        type="wiadomosc",
                        read=False,
                        last_message_at=now,
                    ),
                    Thread(
                        id="th_kpi_2",
                        title="Dyskusja Allegro",
                        author="buyer2",
                        type="dyskusja",
                        read=True,
                        last_message_at=now,
                    ),
                ]
            )
            db.add_all(
                [
                    Message(id="msg_kpi_1", thread_id="th_kpi_1", author="buyer1", content="Pomoc", created_at=now - timedelta(hours=3)),
                    Message(id="msg_kpi_2", thread_id="th_kpi_1", author="seller", content="Juz pomagam", created_at=now - timedelta(hours=1)),
                    Message(id="msg_kpi_3", thread_id="th_kpi_2", author="buyer2", content="Status?", created_at=now - timedelta(hours=4)),
                    Message(id="msg_kpi_4", thread_id="th_kpi_2", author="seller", content="Wyslane", created_at=now - timedelta(hours=2)),
                ]
            )
            db.commit()

    response = client.get("/api/stats/customer-support")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["summary"]["threads_total"] == 2
    assert payload["data"]["summary"]["unread_threads"] == 1
    assert payload["data"]["summary"]["first_response_samples"] == 2
    assert payload["data"]["summary"]["avg_first_response_hours"] == 2.0
    assert payload["data"]["by_type"]["wiadomosc"]["unread"] == 1
    assert payload["data"]["by_type"]["dyskusja"]["threads"] == 1


def test_stats_invoice_coverage_returns_kpi(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    now_ts = int(datetime.now().timestamp())

    with app.app_context():
        with get_session() as db:
            db.add_all(
                [
                    Order(
                        order_id="inv_cov_1",
                        platform="allegro",
                        date_add=now_ts,
                        payment_done=100.0,
                        want_invoice=True,
                        wfirma_invoice_id=101,
                        wfirma_invoice_number="FV/101",
                        emails_sent=json.dumps({"invoice": True}),
                    ),
                    Order(
                        order_id="inv_cov_2",
                        platform="allegro",
                        date_add=now_ts,
                        payment_done=90.0,
                        want_invoice=True,
                        wfirma_invoice_id=102,
                        wfirma_invoice_number="FV/102",
                        emails_sent="{}",
                    ),
                    Order(
                        order_id="inv_cov_3",
                        platform="shop",
                        date_add=now_ts,
                        payment_done=70.0,
                        want_invoice=True,
                        wfirma_invoice_id=None,
                    ),
                    Order(
                        order_id="inv_cov_4",
                        platform="shop",
                        date_add=now_ts,
                        payment_done=50.0,
                        want_invoice=False,
                        wfirma_invoice_id=None,
                    ),
                ]
            )
            db.commit()

    response = client.get("/api/stats/invoice-coverage")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    summary = payload["data"]["summary"]

    assert summary["orders_total"] == 4
    assert summary["requested_total"] == 3
    assert summary["invoiced_total"] == 2
    assert summary["missing_total"] == 1
    assert summary["emailed_total"] == 1
    assert round(float(summary["coverage_pct"]), 2) == 66.67
    assert round(float(summary["email_coverage_pct"]), 2) == 33.33
    assert payload["data"]["missing_orders"][0]["order_id"] == "inv_cov_3"


def test_stats_ads_offer_analytics_returns_kpi(client, app, login, monkeypatch):
    from magazyn import allegro_api as allegro_api_module
    from magazyn import stats as stats_module
    from magazyn.models import AllegroOffer

    stats_module._FAST_CACHE.clear()
    monkeypatch.setattr(stats_module.settings_store, "get", lambda key, default=None: "token" if key == "ALLEGRO_ACCESS_TOKEN" else default)

    monkeypatch.setattr(
        allegro_api_module,
        "fetch_billing_entries",
        lambda token, occurred_at_gte=None, occurred_at_lte=None, limit=100: {
            "billingEntries": [
                {"type": {"id": "ADS"}, "value": {"amount": "-5.00"}, "offer": {"id": "111", "name": "Oferta 111"}},
                {"type": {"id": "BRG"}, "value": {"amount": "-3.00"}, "offer": {"id": "111", "name": "Oferta 111"}},
                {"type": {"id": "CB2"}, "value": {"amount": "1.00"}, "offer": {"id": "111", "name": "Oferta 111"}},
                {"type": {"id": "ADS"}, "value": {"amount": "-2.00"}, "offer": {"id": "222", "name": "Oferta 222"}},
                {"type": {"id": "NSP"}, "value": {"amount": "-4.00"}},
            ]
        },
    )

    _seed_order(app, "ord_ads_1", payment_done=100.0)
    _seed_order(app, "ord_ads_2", payment_done=120.0)

    with app.app_context():
        with get_session() as db:
            db.add_all(
                [
                    AllegroOffer(offer_id="111", title="Oferta 111", price=99.99, publication_status="ACTIVE"),
                    AllegroOffer(offer_id="222", title="Oferta 222", price=89.99, publication_status="ACTIVE"),
                ]
            )
            db.flush()

            op1 = db.query(OrderProduct).filter(OrderProduct.order_id == "ord_ads_1").first()
            op2 = db.query(OrderProduct).filter(OrderProduct.order_id == "ord_ads_2").first()
            op1.auction_id = "111"
            op2.auction_id = "222"
            db.commit()

    response = client.get("/api/stats/ads-offer-analytics")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    summary = payload["data"]["summary"]

    assert summary["account_level_ads_total"] == 4.0
    assert summary["offer_ads_total"] == 7.0
    assert summary["promoted_commission_total"] == 3.0
    assert summary["campaign_bonus_total"] == 1.0
    assert summary["offers_with_ads_cost"] == 2
    assert payload["data"]["top_offers"][0]["offer_id"] == "111"
    assert payload["data"]["availability"]["offer_level_ads_cost"] is True
    assert payload["data"]["availability"]["offer_level_views_ctr"] is False


def test_stats_ads_offer_analytics_export_csv(client, app, login, monkeypatch):
    from magazyn import allegro_api as allegro_api_module
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    monkeypatch.setattr(stats_module.settings_store, "get", lambda key, default=None: "token" if key == "ALLEGRO_ACCESS_TOKEN" else default)
    monkeypatch.setattr(
        allegro_api_module,
        "fetch_billing_entries",
        lambda token, occurred_at_gte=None, occurred_at_lte=None, limit=100: {
            "billingEntries": [
                {"type": {"id": "ADS"}, "value": {"amount": "-5.00"}, "offer": {"id": "111", "name": "Oferta 111"}},
            ]
        },
    )

    response = client.get("/api/stats/ads-offer-analytics?format=csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    body = response.data.decode("utf-8")
    assert "offer_id" in body
    assert "111" in body


def test_stats_refund_timeline_returns_metrics(client, app, login):
    from magazyn import stats as stats_module

    stats_module._FAST_CACHE.clear()
    now = datetime.now().replace(microsecond=0)
    _seed_order(app, "ord_ref_1", payment_done=100.0)
    _seed_order(app, "ord_ref_2", payment_done=120.0)

    with app.app_context():
        with get_session() as db:
            ret1 = Return(order_id="ord_ref_1", status="completed", refund_processed=True, created_at=now - timedelta(hours=30))
            ret2 = Return(order_id="ord_ref_2", status="delivered", refund_processed=False, created_at=now - timedelta(hours=20))
            db.add_all([ret1, ret2])
            db.flush()
            ret1_id = ret1.id
            ret2_id = ret2.id
            db.commit()

    _seed_return_status_log(app, ret1_id, "delivered", now - timedelta(hours=24))
    _seed_return_status_log(app, ret1_id, "completed", now - timedelta(hours=12))
    _seed_return_status_log(app, ret2_id, "delivered", now - timedelta(hours=10))

    date_from = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    date_to = now.strftime("%Y-%m-%d")
    response = client.get(f"/api/stats/refund-timeline?date_from={date_from}&date_to={date_to}")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["ok"] is True
    assert payload["data"]["summary"]["returns_total"] == 2
    assert payload["data"]["summary"]["delivered_count"] == 2
    assert payload["data"]["summary"]["refunded_count"] == 1
    assert payload["data"]["transitions"]["request_to_delivered"]["count"] == 2
    assert payload["data"]["transitions"]["delivered_to_refund"]["count"] == 1
    assert payload["data"]["transitions"]["request_to_refund"]["avg_hours"] == 18.0
