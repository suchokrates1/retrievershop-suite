from datetime import datetime
from decimal import Decimal

from magazyn.db import get_session
from magazyn.domain.dashboard import DashboardService, TimeRanges
from magazyn.models.orders import Order, OrderProduct, OrderStatusLog
from magazyn.settings_store import settings_store


def _add_order(db, order_id, date_add, quantity, profit=None, payment_done=100.0):
    order = Order(
        order_id=order_id,
        platform="allegro",
        date_add=date_add,
        payment_done=payment_done,
        payment_method_cod=False,
        real_profit_amount=profit,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderProduct(
            order_id=order_id,
            name="Produkt testowy",
            quantity=quantity,
            price_brutto=50.0,
        )
    )


def test_get_sales_records_returns_daily_monthly_and_profit_records(app):
    day_a = int(datetime(2026, 3, 10, 12, 0, 0).timestamp())
    day_b = int(datetime(2026, 3, 11, 12, 0, 0).timestamp())
    month_a = int(datetime(2026, 1, 15, 12, 0, 0).timestamp())
    month_b = int(datetime(2026, 2, 15, 12, 0, 0).timestamp())

    with app.app_context():
        with get_session() as db:
            _add_order(db, "ord_day_a_1", day_a, 2, profit=Decimal("10.00"))
            _add_order(db, "ord_day_a_2", day_a, 3, profit=Decimal("12.00"))
            _add_order(db, "ord_day_b_1", day_b, 4, profit=Decimal("8.00"))
            _add_order(db, "ord_month_a_1", month_a, 1, profit=Decimal("40.00"))
            _add_order(db, "ord_month_b_1", month_b, 1, profit=Decimal("5.00"))
            _add_order(db, "ord_month_b_2", month_b, 1, profit=Decimal("6.00"))

        with get_session() as db:
            service = DashboardService(db, settings_store)
            records = service.get_sales_records()

    assert records.daily_date == "10.03.2026"
    assert records.daily_quantity == 5
    assert records.monthly_label == "Marzec 2026"
    assert records.monthly_quantity == 9
    assert records.max_profit_amount == 40.0
    assert records.max_profit_month == "Styczen 2026"


def test_get_sales_records_marks_tied_daily_record_with_egzekwo_count(app):
    days = [
        int(datetime(2026, 3, 1, 12, 0, 0).timestamp()),
        int(datetime(2026, 3, 5, 12, 0, 0).timestamp()),
        int(datetime(2026, 3, 9, 12, 0, 0).timestamp()),
        int(datetime(2026, 3, 12, 12, 0, 0).timestamp()),
        int(datetime(2026, 3, 20, 12, 0, 0).timestamp()),
    ]

    with app.app_context():
        with get_session() as db:
            for idx, day_ts in enumerate(days):
                _add_order(db, f"ord_tie_{idx}", day_ts, 8, profit=Decimal("10.00"))
            _add_order(db, "ord_lower", int(datetime(2026, 3, 21, 12, 0, 0).timestamp()), 3)

        with get_session() as db:
            service = DashboardService(db, settings_store)
            records = service.get_sales_records()

    assert records.daily_quantity == 8
    assert records.daily_date == "20.03.2026 (5)"


def test_get_sales_records_marks_tied_monthly_and_profit_records(app):
    jan = int(datetime(2026, 1, 10, 12, 0, 0).timestamp())
    mar = int(datetime(2026, 3, 10, 12, 0, 0).timestamp())
    may = int(datetime(2026, 5, 10, 12, 0, 0).timestamp())
    feb = int(datetime(2026, 2, 10, 12, 0, 0).timestamp())

    with app.app_context():
        with get_session() as db:
            _add_order(db, "ord_jan", jan, 4, profit=Decimal("100.00"))
            _add_order(db, "ord_mar", mar, 4, profit=Decimal("100.00"))
            _add_order(db, "ord_may", may, 4, profit=Decimal("100.00"))
            _add_order(db, "ord_feb", feb, 1, profit=Decimal("20.00"))

        with get_session() as db:
            service = DashboardService(db, settings_store)
            records = service.get_sales_records()

    assert records.monthly_quantity == 4
    assert records.monthly_label == "Maj 2026 (3)"
    assert records.max_profit_amount == 100.0
    assert records.max_profit_month == "Maj 2026 (3)"


def test_resolve_tied_record_helpers():
    label, value = DashboardService._resolve_tied_record(
        [("2026-03-01", 8), ("2026-03-20", 8), ("2026-03-10", 5)],
        DashboardService._format_day_label,
    )
    assert value == 8
    assert label == "20.03.2026 (2)"

    single_label, single_value = DashboardService._resolve_tied_record(
        [("2026-04-01", 7)],
        DashboardService._format_day_label,
    )
    assert single_value == 7
    assert single_label == "01.04.2026"


def _status(db, order_id, status, when):
    db.add(OrderStatusLog(order_id=order_id, status=status, timestamp=when))


def test_order_stats_skip_unpaid_and_average_uses_day_of_month(app):
    now = datetime(2026, 10, 25, 15, 0, 0)
    today = int(datetime(2026, 10, 25, 9, 0, 0).timestamp())
    week_day = int(datetime(2026, 10, 20, 11, 0, 0).timestamp())
    earlier = int(datetime(2026, 10, 2, 11, 0, 0).timestamp())

    with app.app_context():
        with get_session() as db:
            _add_order(db, "ord_paid_today", today, 1, payment_done=100.0)
            _add_order(db, "ord_unpaid_today", today, 1, payment_done=80.0)
            _add_order(db, "ord_paid_week", week_day, 1, payment_done=40.0)
            _add_order(db, "ord_paid_month", earlier, 1, payment_done=200.0)
            db.flush()
            _status(db, "ord_paid_today", "pobrano", datetime(2026, 10, 25, 9, 5, 0))
            _status(db, "ord_unpaid_today", "pobrano", datetime(2026, 10, 25, 9, 1, 0))
            _status(db, "ord_unpaid_today", "nieoplacone", datetime(2026, 10, 25, 9, 6, 0))
            _status(db, "ord_paid_week", "nieoplacone", datetime(2026, 10, 20, 11, 1, 0))
            _status(db, "ord_paid_week", "pobrano", datetime(2026, 10, 20, 12, 0, 0))
            _status(db, "ord_paid_month", "wydrukowano", datetime(2026, 10, 2, 12, 0, 0))
            db.query(Order).filter(Order.order_id == "ord_paid_month").update(
                {"delivery_package_nr": "PKG1"}
            )

        with get_session() as db:
            service = DashboardService(db, settings_store)
            service.time_ranges = TimeRanges(
                now=now,
                today_start=int(datetime(2026, 10, 25).timestamp()),
                week_start_ts=int(datetime(2026, 10, 19).timestamp()),
                month_start_ts=int(datetime(2026, 10, 1).timestamp()),
                prev_week_start_ts=int(datetime(2026, 10, 12).timestamp()),
                current_month_name="Pazdziernik",
            )
            stats = service.get_order_stats()
            revenue = service.get_revenue_stats()

    assert stats.today == 1
    assert stats.week == 2
    assert stats.month == 3
    assert stats.pending == 2
    assert stats.month_daily_avg == 0.1
    assert revenue.today == 100.0
    assert revenue.week == 140.0
    assert revenue.month == 340.0


def test_daily_order_average_rounds_half_up():
    assert DashboardService._daily_order_average(2, 25) == 0.1
    assert DashboardService._daily_order_average(58, 25) == 2.3
    assert DashboardService._daily_order_average(13, 25) == 0.5
    assert DashboardService._daily_order_average(0, 25) == 0.0


def test_home_page_shows_daily_average_instead_of_order_label(client, login, app):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Średnia:" in html
    assert "Zamówień" not in html


def test_home_page_renders_sales_records_module(client, login, app):
    day_ts = int(datetime(2026, 4, 2, 10, 0, 0).timestamp())
    month_ts = int(datetime(2026, 4, 12, 10, 0, 0).timestamp())

    with app.app_context():
        with get_session() as db:
            _add_order(db, "ord_home_1", day_ts, 7, profit=Decimal("30.00"))
            _add_order(db, "ord_home_2", month_ts, 2, profit=Decimal("15.00"))

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Rekord sprzedaży" in html
    assert "Rekord dzienny:" in html
    assert "Rekord miesięczny:" in html
    assert "Największy realny zysk:" in html
    assert "02.04.2026" in html
    assert "7 szt." in html
