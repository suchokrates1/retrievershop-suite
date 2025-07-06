import magazyn.print_agent as pa


def test_weekly_report_not_sent_when_disabled(monkeypatch):
    monkeypatch.setattr(pa, "ENABLE_WEEKLY_REPORTS", False)
    monkeypatch.setattr(pa, "ENABLE_MONTHLY_REPORTS", False)
    monkeypatch.setattr(pa, "get_sales_summary", lambda *a, **k: [])
    calls = []
    monkeypatch.setattr(pa, "send_report", lambda *a, **k: calls.append(a))
    pa._last_weekly_report = None
    pa._send_periodic_reports()
    assert calls == []

