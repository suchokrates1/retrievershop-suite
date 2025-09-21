import time
import threading
import importlib
import magazyn.print_agent as pa


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
