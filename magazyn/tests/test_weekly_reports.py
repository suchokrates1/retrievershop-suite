import magazyn.print_agent as pa


def test_weekly_report_not_sent_when_disabled(monkeypatch):
    agent = pa.agent
    agent.config = agent.config.with_updates(
        enable_weekly_reports=False,
        enable_monthly_reports=False,
    )
    monkeypatch.setattr(pa, "get_sales_summary", lambda *a, **k: [])
    calls = []
    monkeypatch.setattr(pa, "send_report", lambda *a, **k: calls.append(a))
    agent._last_weekly_report = None
    agent._send_periodic_reports()
    assert calls == []
