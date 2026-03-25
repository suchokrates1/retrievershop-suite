import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

import magazyn.print_agent as pa


def _make_agent(tmp_path):
    config = pa.agent.config.with_updates(
        db_file=str(tmp_path / "agent.db"),
        lock_file=str(tmp_path / "agent.lock"),
        log_file=str(tmp_path / "agent.log"),
        poll_interval=1,
    )
    return pa.LabelAgent(config, pa.settings)


def test_stop_agent_thread_stops(monkeypatch):
    agent = pa.agent
    started = threading.Event()

    def loop():
        started.set()
        while not agent._stop_event.is_set():
            time.sleep(0.01)

    monkeypatch.setattr(agent, "_agent_loop", loop)
    agent.start_agent_thread()
    assert started.wait(1)
    assert agent._agent_thread.is_alive()
    agent.stop_agent_thread()
    assert agent._agent_thread is None or not agent._agent_thread.is_alive()


def test_start_agent_thread_cleans_orphaned_lock(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    agent.ensure_db()
    lock_path = Path(agent.config.lock_file)
    heartbeat_path = Path(agent._heartbeat_path)
    lock_path.write_text("")
    stale = datetime.now() - timedelta(minutes=10)
    heartbeat_path.write_text(stale.isoformat())
    started = threading.Event()

    def loop():
        started.set()
        agent._stop_event.wait(0.05)

    monkeypatch.setattr(agent, "_agent_loop", loop)
    try:
        assert agent.start_agent_thread()
        assert started.wait(1)
        assert heartbeat_path.exists()
        refreshed = datetime.fromisoformat(heartbeat_path.read_text().strip())
        assert refreshed > stale
    finally:
        agent.stop_agent_thread()
        assert not heartbeat_path.exists()
        if lock_path.exists():
            lock_path.unlink()


def test_retry_updates_metrics(tmp_path):
    agent = _make_agent(tmp_path)
    waits = []

    class DummyEvent:
        def wait(self, timeout):
            waits.append(timeout)
            return False

        def is_set(self):
            return False

    agent._stop_event = DummyEvent()
    attempts = []
    start_retries = pa.PRINT_AGENT_RETRIES_TOTAL._value.get()
    start_downtime = pa.PRINT_AGENT_DOWNTIME_SECONDS._value.get()

    def flaky():
        attempts.append(object())
        if len(attempts) < 3:
            raise pa.PrintError("fail")
        return "ok"

    result = agent._retry(
        flaky,
        stage="test",
        retry_exceptions=(pa.PrintError,),
        max_attempts=3,
        base_delay=0.5,
    )

    assert result == "ok"
    assert len(attempts) == 3
    assert waits == [0.5, 1.0]
    assert pa.PRINT_AGENT_RETRIES_TOTAL._value.get() == start_retries + 2
    assert pa.PRINT_AGENT_DOWNTIME_SECONDS._value.get() == start_downtime + 1.5


def test_retry_does_not_retry_shipment_expired(tmp_path):
    """ShipmentExpiredError nie powinien byc retryowany - natychmiastowy raise."""
    agent = _make_agent(tmp_path)
    agent._stop_event = threading.Event()
    attempts = []

    def always_expired():
        attempts.append(1)
        raise pa.ShipmentExpiredError("test-shipment-id")

    import pytest
    with pytest.raises(pa.ShipmentExpiredError):
        agent._retry(
            always_expired,
            stage="label",
            retry_exceptions=(pa.ApiError,),
            max_attempts=3,
        )

    # Powinien byc wywolany tylko raz - bez retry
    assert len(attempts) == 1


def test_recreate_shipment_and_get_label(tmp_path, monkeypatch):
    """Test cancel + recreate + get_label flow."""
    agent = _make_agent(tmp_path)
    agent.last_order_data = {
        "order_id": "allegro_test-uuid",
        "delivery_method": "InPost Paczkomaty",
        "delivery_fullname": "Jan Kowalski",
        "delivery_address": "ul. Testowa 1",
        "delivery_city": "Warszawa",
        "delivery_postcode": "00-001",
        "delivery_country_code": "PL",
        "phone": "500000000",
        "email": "test@test.pl",
        "products": [{"name": "Produkt testowy", "quantity": 1}],
    }

    cancel_called = []
    monkeypatch.setattr(
        pa, "cancel_shipment",
        lambda sid: cancel_called.append(sid),
    )

    new_packages = [
        {"shipment_id": "new-ship-123", "waybill": "WAY123", "carrier_id": "INPOST"}
    ]
    monkeypatch.setattr(
        agent, "_create_allegro_shipment",
        lambda oid, cfid: new_packages,
    )

    monkeypatch.setattr(
        agent, "get_label",
        lambda cc, pid: ("base64data", "pdf"),
    )

    package_ids = ["old-ship-expired"]
    tracking_numbers = []

    label_data, ext = agent._recreate_shipment_and_get_label(
        "allegro_test-uuid", "old-ship-expired", "INPOST",
        package_ids, tracking_numbers,
    )

    assert label_data == "base64data"
    assert ext == "pdf"
    assert cancel_called == ["old-ship-expired"]
    assert "old-ship-expired" not in package_ids
    assert "new-ship-123" in package_ids
    assert "WAY123" in tracking_numbers
