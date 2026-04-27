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
    monkeypatch.setattr(agent, "consume_order_stock", lambda p: None)
    monkeypatch.setattr(
        agent,
        "print_label",
        lambda d, e, o: None,
    )

    captured = {}
    monkeypatch.setattr(agent, "mark_as_printed", lambda oid, data=None: captured.setdefault("marked", data))
    monkeypatch.setattr(
        agent,
        "send_messenger_message",
        lambda data, print_success=True: captured.setdefault("mess", data),
    )

    monkeypatch.setattr(agent, "get_orders", lambda: [{"order_id": 1, "products": [{"name": "Prod", "quantity": 1}], "payment_done": 100.0}])
    monkeypatch.setattr(agent, "get_order_packages", lambda oid: [{"shipment_id": "s1", "carrier_id": "DHL", "waybill": "WB123"}])
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


def test_agent_loop_treats_pobranie_as_cod_with_zero_payment(monkeypatch):
    mod = importlib.reload(pa)
    agent = mod.agent

    monkeypatch.setattr(agent, "_send_periodic_reports", lambda: None)
    monkeypatch.setattr(agent, "clean_old_printed_orders", lambda: None)
    monkeypatch.setattr(agent, "load_printed_orders", lambda: [])
    monkeypatch.setattr(agent, "load_queue", lambda: [])
    monkeypatch.setattr(agent, "save_queue", lambda q: None)
    monkeypatch.setattr(agent, "is_quiet_time", lambda: False)
    monkeypatch.setattr(agent, "consume_order_stock", lambda p: None)
    monkeypatch.setattr(agent, "print_label", lambda d, e, o: None)

    captured = {}
    monkeypatch.setattr(agent, "mark_as_printed", lambda oid, data=None: captured.setdefault("marked", data))
    monkeypatch.setattr(agent, "send_messenger_message", lambda data, print_success=True: captured.setdefault("mess", data))

    monkeypatch.setattr(
        agent,
        "get_orders",
        lambda: [
            {
                "order_id": 2,
                "products": [{"name": "Prod", "quantity": 1}],
                "payment_done": 0.0,
                "payment_method_cod": "0",
                "payment_method": "Pobranie przy odbiorze",
            }
        ],
    )
    monkeypatch.setattr(agent, "get_order_packages", lambda oid: [{"shipment_id": "s1", "carrier_id": "DHL", "waybill": "WB124"}])
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

    assert agent.last_order_data.get("payment_method") == "Pobranie przy odbiorze"
    assert captured["mess"].get("courier_code") == "DHL"
    assert captured["marked"].get("courier_code") == "DHL"


def test_get_orders_includes_blad_druku_under_3_retries(app):
    """get_orders zwraca zamowienia z blad_druku gdy error_count < 3."""
    from magazyn.db import get_session
    from magazyn.models.orders import Order, OrderStatusLog
    import time

    oid = "allegro_test-retry-blad"
    now_ts = int(time.time())

    with app.app_context():
        with get_session() as db:
            order = Order(
                order_id=oid,
                platform="allegro",
                date_add=now_ts,
                delivery_fullname="Test Retry",
            )
            db.add(order)
            # 1x blad_druku - powinno byc jeszcze retry
            db.add(OrderStatusLog(order_id=oid, status="blad_druku", notes="test"))
            db.commit()

        mod = importlib.reload(pa)
        agent = mod.agent
        orders = agent.get_orders()
        order_ids = [o["order_id"] for o in orders]
        assert oid in order_ids

        # Dodaj jeszcze 2x blad_druku (lacznie 3) - powinno byc pominiete
        with get_session() as db:
            db.add(OrderStatusLog(order_id=oid, status="blad_druku", notes="test2"))
            db.add(OrderStatusLog(order_id=oid, status="blad_druku", notes="test3"))
            db.commit()

        orders = agent.get_orders()
        order_ids = [o["order_id"] for o in orders]
        assert oid not in order_ids
