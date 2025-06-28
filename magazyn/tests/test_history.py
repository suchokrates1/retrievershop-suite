import importlib
from datetime import datetime


def test_history_page_shows_reprint_form(app_mod, client, login, monkeypatch):
    monkeypatch.setattr(app_mod.print_agent, "load_printed_orders", lambda: {"1": datetime.now()})
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
    monkeypatch.setattr(app_mod.print_agent, "load_queue", lambda: [{"order_id": "2", "label_data": "x", "ext": "pdf"}])
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
