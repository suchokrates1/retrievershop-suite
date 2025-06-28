import time
import threading
import importlib
import magazyn.print_agent as pa


def test_stop_agent_thread_stops(monkeypatch):
    started = threading.Event()

    def loop():
        started.set()
        while not pa._stop_event.is_set():
            time.sleep(0.01)

    monkeypatch.setattr(pa, "_agent_loop", loop)
    pa.start_agent_thread()
    assert started.wait(1)
    assert pa._agent_thread.is_alive()
    pa.stop_agent_thread()
    assert pa._agent_thread is None or not pa._agent_thread.is_alive()
