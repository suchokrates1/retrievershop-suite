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
    app_mod.consume_stock(prod.id, "M", 2)
    assert alerts and alerts[0][2] == 1


def test_sales_summary(app_mod, monkeypatch):
    monkeypatch.setattr(cfg.settings, "LOW_STOCK_THRESHOLD", 1)
    services = importlib.import_module("magazyn.services")
    importlib.reload(services)
    prod = services.create_product("Prod", "Red", {"M": 0}, {"M": "111"})
    app_mod.record_purchase(prod.id, "M", 5, 1.0)
    app_mod.consume_stock(prod.id, "M", 2)
    summary = services.get_sales_summary(7)
    assert summary[0]["sold"] == 2
    assert summary[0]["remaining"] == 3
