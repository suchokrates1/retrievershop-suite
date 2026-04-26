from decimal import Decimal

from magazyn.domain.price_report_profit import build_fallback_profit_data, build_profit_data


def test_build_profit_data_includes_purchase_shipping_and_packaging_costs():
    data = build_profit_data(
        our_price=Decimal("100"),
        competitor_price=Decimal("90"),
        purchase_price=Decimal("20"),
        shipping_cost=Decimal("5"),
        packaging_cost=Decimal("1"),
    )

    assert data == {
        "current_price": 100.0,
        "target_price": 89.99,
        "price_change_percent": 10.01,
        "current_profit": 60.7,
        "new_profit": 51.92,
        "profit_change": -8.78,
        "purchase_price": 20.0,
        "competitor_price": 90.0,
    }


def test_build_fallback_profit_data_marks_missing_purchase_cost():
    data = build_fallback_profit_data(Decimal("100"), Decimal("90"))

    assert data["purchase_price"] is None
    assert data["current_profit"] == 77.55
    assert data["new_profit"] == 68.77
    assert data["note"] == "Brak danych o cenie zakupu - pokazano zysk bez kosztu towaru"