import importlib
import magazyn.config as cfg
import magazyn.db as db_mod


def test_low_stock_alert(app_mod, monkeypatch):
    alerts = []
    monkeypatch.setattr(
        db_mod, "send_stock_alert", lambda *a, **k: alerts.append(a)
    )
    monkeypatch.setattr(cfg.settings, "LOW_STOCK_THRESHOLD", 2)
    services = importlib.import_module("magazyn.services")
    importlib.reload(services)
    prod = services.create_product("Prod", "Red", {"M": 0}, {"M": "111"})
    app_mod.record_purchase(prod.id, "M", 3, 1.0)
    app_mod.consume_stock(prod.id, "M", 2, sale_price=0)
    assert alerts and alerts[0][2] == 1


def test_sales_summary(app_mod, monkeypatch):
    monkeypatch.setattr(cfg.settings, "LOW_STOCK_THRESHOLD", 1)
    services = importlib.import_module("magazyn.services")
    importlib.reload(services)
    prod = services.create_product(
        "Prod", "Red", {"M": 0, "L": 0}, {"M": "111", "L": "222"}
    )
    app_mod.record_purchase(prod.id, "M", 5, 1.0)
    app_mod.record_purchase(prod.id, "L", 4, 1.0)
    app_mod.consume_stock(prod.id, "M", 2, sale_price=0)
    app_mod.consume_stock(prod.id, "L", 1, sale_price=0)

    summary = services.get_sales_summary(7)
    summary_map = {(row["name"], row["size"]): row for row in summary}

    assert summary_map[("Prod", "M")]["sold"] == 2
    assert summary_map[("Prod", "M")]["remaining"] == 3
    assert summary_map[("Prod", "L")]["sold"] == 1
    assert summary_map[("Prod", "L")]["remaining"] == 3
