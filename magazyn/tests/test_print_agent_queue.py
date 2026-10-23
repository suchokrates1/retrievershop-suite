"""Kolejka etykiet nie drukuje drugi raz zamowienia juz oznaczonego jako wydrukowane."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

from magazyn.services.print_agent_queue import PrintQueueProcessor


def _processor(**overrides) -> PrintQueueProcessor:
    defaults = {
        "logger": Mock(),
        "is_quiet_time": Mock(return_value=False),
        "save_queue": Mock(),
        "mark_as_printed": Mock(),
        "notify_messenger": Mock(),
        "retry": lambda func, *args, **kwargs: func(*args),
        "print_label": Mock(),
        "claim_print": Mock(return_value=True),
        "release_print_claim": Mock(),
        "print_error_type": Exception,
        "errors_total": Mock(),
        "now": lambda: datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return PrintQueueProcessor(**defaults)


def _item(order_id: str, retry_count: int) -> dict:
    return {
        "order_id": order_id,
        "label_data": "bGFiZWw=",
        "ext": "pdf",
        "last_order_data": {"products": []},
        "queued_at": "2026-10-20T11:25:55",
        "status": "queued",
        "retry_count": retry_count,
    }


def test_second_claim_is_dropped_without_print_or_messenger():
    print_label = Mock()
    notify = Mock()
    processor = _processor(
        print_label=print_label,
        notify_messenger=notify,
        claim_print=Mock(return_value=False),
    )

    left = processor.process([_item("allegro_1", 0)], {})

    assert left == []
    print_label.assert_not_called()
    notify.assert_not_called()


def test_quiet_time_marker_with_zero_retries_still_prints_once():
    print_label = Mock()
    notify = Mock()
    consume = Mock()
    processor = _processor(print_label=print_label, notify_messenger=notify)
    printed = {"allegro_1": datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)}

    left = processor.process([_item("allegro_1", 0)], printed)

    assert left == []
    print_label.assert_called_once()
    notify.assert_called_once()
    consume.assert_not_called()


def test_failed_print_releases_claim():
    release = Mock()

    def fail_print(*_args, **_kwargs):
        raise RuntimeError("cups")

    processor = _processor(print_label=fail_print, release_print_claim=release)

    left = processor.process([_item("allegro_1", 0)], {})

    assert len(left) == 1
    assert left[0]["retry_count"] == 1
    release.assert_called_once_with("allegro_1")
