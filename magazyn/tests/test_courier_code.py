import importlib
import magazyn.print_agent as pa


def test_agent_loop_stores_courier_code(monkeypatch):
    mod = importlib.reload(pa)
    agent = mod.agent

    monkeypatch.setattr(agent, "_send_periodic_reports", lambda: None)
    monkeypatch.setattr(agent, "clean_old_printed_orders", lambda: None)
    monkeypatch.setattr(agent, "load_printed_orders", lambda: [])
    monkeypatch.setattr(agent, "load_queue", lambda: [])
    monkeypatch.setattr(agent, "save_queue", lambda q: None)
    monkeypatch.setattr(agent, "is_quiet_time", lambda: False)
    monkeypatch.setattr(mod, "consume_order_stock", lambda p: None)
    monkeypatch.setattr(
        agent,
        "print_label",
        lambda d, e, o: None,
    )

    captured = {}
    monkeypatch.setattr(agent, "mark_as_printed", lambda oid, data=None: captured.setdefault("marked", data))
    monkeypatch.setattr(agent, "send_messenger_message", lambda data: captured.setdefault("mess", data))

    monkeypatch.setattr(agent, "get_orders", lambda: [{"order_id": 1, "products": [{"name": "Prod", "quantity": 1}]}])
    monkeypatch.setattr(agent, "get_order_packages", lambda oid: [{"package_id": "p1", "courier_code": "DHL"}])
    monkeypatch.setattr(agent, "get_label", lambda code, pid: ("data", "pdf"))

    class Stopper:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            return self.calls > 0

        def wait(self, t):
            self.calls += 1
    agent._stop_event = Stopper()
    agent.config = agent.config.with_updates(poll_interval=0)

    agent._agent_loop()

    assert agent.last_order_data.get("courier_code") == "DHL"
    assert captured["mess"].get("courier_code") == "DHL"
    assert captured["marked"].get("courier_code") == "DHL"
