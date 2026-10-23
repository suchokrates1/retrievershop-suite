"""Testy soft-skip przy niepełnych danych odbiorcy."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

from magazyn.services.print_agent_errors import IncompleteReceiverData
from magazyn.services.print_agent_order_processor import (
    PrintOrderProcessor,
    should_soft_skip_incomplete_receiver,
)


def test_should_soft_skip_young_order():
    now = datetime(2026, 8, 2, 17, 45, tzinfo=timezone.utc)
    date_add = int(now.timestamp()) - 5 * 60
    assert should_soft_skip_incomplete_receiver({"date_add": date_add}, now=now)


def test_should_not_soft_skip_old_order():
    now = datetime(2026, 8, 2, 17, 45, tzinfo=timezone.utc)
    date_add = int(now.timestamp()) - 25 * 60
    assert not should_soft_skip_incomplete_receiver({"date_add": date_add}, now=now)


def test_should_not_soft_skip_without_date_add():
    now = datetime(2026, 8, 2, 17, 45, tzinfo=timezone.utc)
    assert not should_soft_skip_incomplete_receiver({}, now=now)


def _processor(**overrides) -> PrintOrderProcessor:
    defaults = {
        "logger": Mock(),
        "set_last_order_data": Mock(),
        "retry": lambda func, *args, **kwargs: func(*args),
        "get_order_packages": Mock(),
        "collect_order_labels": Mock(),
        "is_quiet_time": Mock(return_value=False),
        "save_queue": Mock(),
        "print_label": Mock(),
        "mark_as_printed": Mock(),
        "notify_messenger": Mock(),
        "should_send_error_notification": Mock(return_value=True),
        "send_label_error_notification": Mock(),
        "increment_error_notification": Mock(),
        "wait": Mock(),
        "errors_total": Mock(),
        "print_error_type": Exception,
        "now": lambda: datetime(2026, 8, 2, 17, 45, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return PrintOrderProcessor(**defaults)


def test_process_soft_skips_incomplete_receiver_for_young_order(monkeypatch):
    now = datetime(2026, 8, 2, 17, 45, tzinfo=timezone.utc)
    date_add = int(now.timestamp()) - 3 * 60
    get_packages = Mock(
        side_effect=IncompleteReceiverData("allegro_x", "brak telefonu")
    )
    wait = Mock()
    send_notify = Mock()
    processor = _processor(
        get_order_packages=get_packages,
        wait=wait,
        send_label_error_notification=send_notify,
        now=lambda: now,
    )

    status_calls = []
    monkeypatch.setattr(
        "magazyn.services.print_agent_order_processor.set_print_error_status",
        lambda *args, **kwargs: status_calls.append(args),
    )

    processor.process(
        {
            "order_id": "allegro_x",
            "payment_done": 58,
            "payment_method_cod": "0",
            "payment_method": "Przelew online",
            "date_add": date_add,
            "products": [],
        },
        queue=[],
        printed={},
    )

    wait.assert_called_once_with(60)
    send_notify.assert_not_called()
    assert status_calls == []


def test_process_escalates_incomplete_receiver_after_timeout(monkeypatch):
    now = datetime(2026, 8, 2, 17, 45, tzinfo=timezone.utc)
    date_add = int(now.timestamp()) - 25 * 60
    get_packages = Mock(
        side_effect=IncompleteReceiverData("allegro_y", "brak telefonu")
    )
    wait = Mock()
    send_notify = Mock()
    errors_total = Mock()
    processor = _processor(
        get_order_packages=get_packages,
        wait=wait,
        send_label_error_notification=send_notify,
        should_send_error_notification=Mock(return_value=True),
        errors_total=errors_total,
        now=lambda: now,
    )

    status_calls = []
    monkeypatch.setattr(
        "magazyn.services.print_agent_order_processor.set_print_error_status",
        lambda *args, **kwargs: status_calls.append(args),
    )

    processor.process(
        {
            "order_id": "allegro_y",
            "payment_done": 58,
            "payment_method_cod": "0",
            "payment_method": "Przelew online",
            "date_add": date_add,
            "products": [],
        },
        queue=[],
        printed={},
    )

    wait.assert_called_once_with(60)
    send_notify.assert_called_once_with("allegro_y")
    assert len(status_calls) == 1
    assert status_calls[0][0] == "allegro_y"
    assert "po 20 min" in status_calls[0][1]
    errors_total.labels.assert_called_with(stage="label")


def test_enqueue_labels_does_not_print_or_take_stock():
    print_label = Mock()
    notify = Mock()
    mark = Mock()
    processor = _processor(
        print_label=print_label,
        notify_messenger=notify,
        mark_as_printed=mark,
    )
    queue: list = []
    printed: dict = {}

    processor._enqueue_labels(
        "allegro_ok",
        {"products": [{"name": "Szelki", "quantity": 1}]},
        [("bGFiZWw=", "pdf")],
        queue,
        printed,
    )

    print_label.assert_not_called()
    notify.assert_not_called()
    mark.assert_called_once()
    assert queue[0]["status"] == "queued"
    assert "allegro_ok" in printed


def test_print_labels_now_notifies_messenger_only_after_success(monkeypatch):
    notify = Mock()
    processor = _processor(notify_messenger=notify)
    printed: dict = {}
    queue: list = []

    processor._print_labels_now(
        "allegro_ok",
        {"products": []},
        [("bGFiZWw=", "pdf")],
        queue,
        printed,
    )

    notify.assert_called_once_with({"products": []}, True)
    assert "allegro_ok" in printed
    assert queue == []


def test_print_labels_now_skips_messenger_when_print_fails(monkeypatch):
    notify = Mock()

    def fail_print(*_args, **_kwargs):
        raise RuntimeError("timeout")

    processor = _processor(notify_messenger=notify, print_label=fail_print)
    monkeypatch.setattr(
        "magazyn.services.print_agent_order_processor.set_print_error_status",
        lambda *_args, **_kwargs: None,
    )
    queue: list = []

    processor._print_labels_now(
        "allegro_fail",
        {"products": []},
        [("bGFiZWw=", "pdf")],
        queue,
        {},
    )

    notify.assert_not_called()
    assert queue and queue[0]["status"] == "queued"
