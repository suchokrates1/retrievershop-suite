"""Runtime cache i telemetria dla API statystyk."""

from __future__ import annotations

import time
from collections import defaultdict


FAST_CACHE_TTL_SECONDS = 60
FAST_CACHE: dict[str, tuple[float, dict]] = {}
TELEMETRY: dict[str, dict[str, float]] = defaultdict(
    lambda: {
        "requests": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "total_response_ms": 0.0,
    }
)


def endpoint_name(cache_key: str) -> str:
    return cache_key.split("|", 1)[0] if "|" in cache_key else "overview"


def cache_get(key: str) -> dict | None:
    item = FAST_CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if time.time() > expires_at:
        FAST_CACHE.pop(key, None)
        return None
    return payload


def cache_set(key: str, payload: dict) -> None:
    FAST_CACHE[key] = (time.time() + FAST_CACHE_TTL_SECONDS, payload)


def record_telemetry(endpoint: str, cache_state: str, started_at: float) -> float:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    entry = TELEMETRY[endpoint]
    entry["requests"] += 1
    entry["total_response_ms"] += elapsed_ms
    if cache_state == "hit":
        entry["cache_hits"] += 1
    else:
        entry["cache_misses"] += 1
    return elapsed_ms


def telemetry_stats(endpoint: str, response_ms: float) -> dict[str, float]:
    entry = TELEMETRY[endpoint]
    requests_total = entry["requests"] or 1
    cache_ratio = (entry["cache_hits"] / requests_total) * 100
    avg_response = entry["total_response_ms"] / requests_total
    return {
        "response_ms": response_ms,
        "avg_response_ms": round(avg_response, 2),
        "cache_hit_ratio": round(cache_ratio, 2),
    }


__all__ = [
    "FAST_CACHE",
    "FAST_CACHE_TTL_SECONDS",
    "TELEMETRY",
    "cache_get",
    "cache_set",
    "endpoint_name",
    "record_telemetry",
    "telemetry_stats",
]