from datetime import datetime


def test_history_page_shows_reprint_form(app_mod, client, login, monkeypatch):
    ts = datetime(2023, 1, 2, 3, 4)
    item = {"order_id": "1", "printed_at": ts, "last_order_data": {"name": "N", "color": "C", "size": "S"}}
    monkeypatch.setattr(app_mod.print_agent, "load_printed_orders", lambda: [item])
    monkeypatch.setattr(app_mod.print_agent, "load_queue", lambda: [])
    resp = client.get("/history")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "/history/reprint/1" in html
    from flask import session as flask_session
    with client.session_transaction() as sess:
        with app_mod.app.test_request_context():
            for k, v in sess.items():
                flask_session[k] = v
            token = app_mod.app.jinja_env.globals["csrf_token"]()
    assert token in html
    assert ts.strftime('%Y-%m-%d %H:%M') in html
    assert "N" in html
    assert "C" in html
    assert "S" in html


def test_reprint_route_uses_api(app_mod, client, login, monkeypatch):
    monkeypatch.setattr(app_mod.print_agent, "load_queue", lambda: [])
    monkeypatch.setattr(app_mod.print_agent, "get_order_packages", lambda oid: [{"package_id": "p1", "courier_code": "c1"}])
    monkeypatch.setattr(app_mod.print_agent, "get_label", lambda code, pid: ("data", "pdf"))
    called = {"n": 0}
    def fake_print(data, ext, oid):
        called["n"] += 1
    monkeypatch.setattr(app_mod.print_agent, "print_label", fake_print)
    mprinted = {"n": 0}
    monkeypatch.setattr(app_mod.print_agent, "mark_as_printed", lambda oid: mprinted.update(n=mprinted["n"] + 1))
    resp = client.post("/history/reprint/1")
    assert resp.status_code == 302
    assert called["n"] == 1
    assert mprinted["n"] == 1

def test_reprint_route_uses_queue(app_mod, client, login, monkeypatch):
    monkeypatch.setattr(app_mod.print_agent, "load_queue", lambda: [{"order_id": "2", "label_data": "x", "ext": "pdf", "last_order_data": {}}])
    called = {"n": 0}
    monkeypatch.setattr(app_mod.print_agent, "print_label", lambda d, e, o: called.update(n=called["n"] + 1))
    saved = {"n": 0}
    monkeypatch.setattr(app_mod.print_agent, "save_queue", lambda items: saved.update(n=saved["n"] + 1))
    marked = {"n": 0}
    monkeypatch.setattr(app_mod.print_agent, "mark_as_printed", lambda oid: marked.update(n=marked["n"] + 1))
    resp = client.post("/history/reprint/2")
    assert resp.status_code == 302
    assert called["n"] == 1
    assert saved["n"] == 1
    assert marked["n"] == 1


def test_reprint_logs_exception(app_mod, client, login, monkeypatch):
    def raise_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(app_mod.print_agent, "load_queue", raise_error)

    logged = {}

    class DummyLogger:
        def exception(self, msg, order_id):
            logged["msg"] = msg
            logged["order_id"] = order_id

    import importlib
    hist_mod = importlib.import_module("magazyn.history")
    monkeypatch.setattr(hist_mod, "logger", DummyLogger())

    resp = client.post("/history/reprint/9")
    assert resp.status_code == 302
    assert logged == {"msg": "Reprint failed for %s", "order_id": "9"}
    with client.session_transaction() as sess:
        msgs = sess.get("_flashes")
    assert any("Błąd ponownego drukowania" in m for _, m in msgs)
