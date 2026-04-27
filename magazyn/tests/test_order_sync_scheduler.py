from types import SimpleNamespace

from magazyn.order_sync_scheduler import _is_http_status


def test_is_http_status_reads_response_status_code():
    exc = RuntimeError("checkout-form missing")
    exc.response = SimpleNamespace(status_code=404)

    assert _is_http_status(exc, 404) is True
    assert _is_http_status(exc, 500) is False


def test_is_http_status_handles_exceptions_without_response():
    assert _is_http_status(RuntimeError("network error"), 404) is False