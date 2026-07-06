from datetime import datetime
from decimal import Decimal

from magazyn.db import get_session
from magazyn.domain.dashboard import DashboardService
from magazyn.models.orders import Order, OrderProduct
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
