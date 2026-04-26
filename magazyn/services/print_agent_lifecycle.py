"""Cykl zycia watku print agenta i jego workerow."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

WorkerFactory = Callable[[Any], Any]


def start_agent_thread(agent: Any, *, worker_factories: Iterable[WorkerFactory]) -> bool:
    if agent._agent_thread and agent._agent_thread.is_alive():
        return False

    if not agent._heartbeat_lock.acquire():
        agent.logger.info("Print agent already running, skipping startup")
        return False

    agent._lock_handle = agent._heartbeat_lock.lock_handle
    agent._stop_event = agent._thread_runtime.stop_event
    if not agent._thread_runtime.start(
        agent._agent_loop,
        already_running_message="Print agent already running",
        started_message="Print agent thread started",
    ):
        agent._heartbeat_lock.release()
        agent._lock_handle = None
        return False

    agent._agent_thread = agent._thread_runtime.thread
    agent._workers = [factory(agent) for factory in worker_factories]
    for worker in agent._workers:
        worker.start()
        agent.logger.info("Uruchomiono worker: %s", worker.name)

    return True


def stop_agent_thread(agent: Any, *, token_refresher: Any) -> None:
    for worker in agent._workers:
        worker.stop()
        agent.logger.info("Zatrzymano worker: %s", worker.name)
    agent._workers = []

    agent._thread_runtime.stop(
        stopping_message="Stopping print agent thread...",
        stopped_message="Print agent thread stopped",
    )
    agent._agent_thread = None
    agent._heartbeat_lock.release()
    agent._lock_handle = None
    token_refresher.stop()


__all__ = ["start_agent_thread", "stop_agent_thread"]
