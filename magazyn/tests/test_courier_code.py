import importlib
import magazyn.print_agent as pa


def test_agent_loop_stores_courier_code(monkeypatch):
    mod = importlib.reload(pa)

    monkeypatch.setattr(mod, "_send_periodic_reports", lambda: None)
    monkeypatch.setattr(mod, "clean_old_printed_orders", lambda: None)
    monkeypatch.setattr(mod, "load_printed_orders", lambda: [])
    monkeypatch.setattr(mod, "load_queue", lambda: [])
    monkeypatch.setattr(mod, "save_queue", lambda q: None)
    monkeypatch.setattr(mod, "is_quiet_time", lambda: False)
    monkeypatch.setattr(mod, "consume_order_stock", lambda p: None)
    monkeypatch.setattr(mod, "print_label", lambda d, e, o: None)

    captured = {}
    monkeypatch.setattr(mod, "mark_as_printed", lambda oid, data=None: captured.setdefault("marked", data))
    monkeypatch.setattr(mod, "send_messenger_message", lambda data: captured.setdefault("mess", data))

    monkeypatch.setattr(mod, "get_orders", lambda: [{"order_id": 1, "products": [{"name": "Prod", "quantity": 1}]}])
    monkeypatch.setattr(mod, "get_order_packages", lambda oid: [{"package_id": "p1", "courier_code": "DHL"}])
    monkeypatch.setattr(mod, "get_label", lambda code, pid: ("data", "pdf"))

    class Stopper:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            return self.calls > 0

        def wait(self, t):
            self.calls += 1
    mod._stop_event = Stopper()
    mod.POLL_INTERVAL = 0

    mod._agent_loop()

    assert mod.last_order_data.get("courier_code") == "DHL"
    assert captured["mess"].get("courier_code") == "DHL"
    assert captured["marked"].get("courier_code") == "DHL"
