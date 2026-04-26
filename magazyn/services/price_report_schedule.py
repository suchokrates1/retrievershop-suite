"""Harmonogramowanie partii raportow cenowych."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List


def is_night_pause_at(now: datetime, *, night_start: int, night_end: int) -> bool:
    return night_start <= now.hour < night_end


def calculate_schedule(
    total_offers: int,
    start_time: datetime,
    end_time: datetime,
    *,
    batch_size: int,
    night_pause_start: int,
    night_pause_end: int,
) -> List[datetime]:
    """Oblicza harmonogram sprawdzania ofert z pominieciem przerwy nocnej."""
    if total_offers <= 0:
        return []

    available_slots = []
    current = start_time
    while current < end_time:
        if not is_night_pause_at(
            current,
            night_start=night_pause_start,
            night_end=night_pause_end,
        ):
            available_slots.append(current)
        current += timedelta(minutes=15)

    if not available_slots:
        return []

    num_batches = (total_offers + batch_size - 1) // batch_size
    if num_batches >= len(available_slots):
        schedule = available_slots[:num_batches]
    else:
        step = len(available_slots) / num_batches
        schedule = []
        for index in range(num_batches):
            base_idx = int(index * step)
            jitter = random.randint(-2, 2)  # nosec B311
            idx = max(0, min(len(available_slots) - 1, base_idx + jitter))
            schedule.append(available_slots[idx])

    final_schedule = []
    for slot in schedule:
        jitter_minutes = random.randint(0, 14)  # nosec B311
        final_schedule.append(slot + timedelta(minutes=jitter_minutes))

    return sorted(final_schedule)


__all__ = ["calculate_schedule", "is_night_pause_at"]