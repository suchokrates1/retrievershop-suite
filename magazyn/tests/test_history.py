from datetime import datetime
import json
import sqlite3

import magazyn.db as db_mod


def test_history_page_shows_reprint_form(app_mod, client, login, monkeypatch):
    ts = datetime(2023, 1, 2, 3, 4)
    item = {
        "order_id": "1",
        "printed_at": ts,
        "last_order_data": {"name": "N", "color": "C", "size": "S", "courier_code": "K"},
    }
    monkeypatch.setattr(
        app_mod.print_agent, "load_printed_orders", lambda: [item]
    )
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
    assert ts.strftime("%d/%m/%Y %H:%M") in html
    assert "N" in html
    assert "C" in html
    assert "S" in html
    assert "K" in html


def test_reprint_route_uses_api(app_mod, client, login, monkeypatch):
    monkeypatch.setattr(app_mod.print_agent, "load_queue", lambda: [])
    monkeypatch.setattr(
        app_mod.print_agent,
        "get_order_packages",
        lambda oid: [{"package_id": "p1", "courier_code": "c1"}],
    )
    monkeypatch.setattr(
        app_mod.print_agent, "get_label", lambda code, pid: ("data", "pdf")
    )
    printed_item = {
        "order_id": "1",
        "printed_at": datetime(2023, 1, 1, 0, 0),
        "last_order_data": {"name": "P", "color": "C", "size": "S"},
    }
    monkeypatch.setattr(
        app_mod.print_agent, "load_printed_orders", lambda: [printed_item]
    )
    called = {"n": 0}

    def fake_print(data, ext, oid):
        called["n"] += 1

    monkeypatch.setattr(app_mod.print_agent, "print_label", fake_print)
    mprinted = {}
    monkeypatch.setattr(
        app_mod.print_agent,
        "mark_as_printed",
        lambda oid, data=None: mprinted.update({"oid": oid, "data": data}),
    )
    resp = client.post("/history/reprint/1")
    assert resp.status_code == 302
    assert called["n"] == 1
    assert mprinted == {"oid": "1", "data": printed_item["last_order_data"]}


def test_reprint_route_uses_queue(app_mod, client, login, monkeypatch):
    monkeypatch.setattr(
        app_mod.print_agent,
        "load_queue",
        lambda: [
            {
                "order_id": "2",
                "label_data": "x",
                "ext": "pdf",
                "last_order_data": {"name": "Q", "color": "C", "size": "S"},
            }
        ],
    )
    called = {"n": 0}
    monkeypatch.setattr(
        app_mod.print_agent,
        "print_label",
        lambda d, e, o: called.update(n=called["n"] + 1),
    )
    saved = {"n": 0}
    monkeypatch.setattr(
        app_mod.print_agent,
        "save_queue",
        lambda items: saved.update(n=saved["n"] + 1),
    )
    marked = {}
    monkeypatch.setattr(
        app_mod.print_agent,
        "mark_as_printed",
        lambda oid, data=None: marked.update({"oid": oid, "data": data}),
    )
    resp = client.post("/history/reprint/2")
    assert resp.status_code == 302
    assert called["n"] == 1
    assert saved["n"] == 1
    assert marked == {
        "oid": "2",
        "data": {"name": "Q", "color": "C", "size": "S"},
    }


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


def test_history_readonly_db(app_mod, client, login, tmp_path, monkeypatch, caplog):
    db_file = tmp_path / "readonly.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "CREATE TABLE printed_orders("  # noqa: S608 - static SQL
            "order_id TEXT PRIMARY KEY, printed_at TEXT, last_order_data TEXT)"
        )
        conn.execute(
            "CREATE TABLE label_queue("  # noqa: S608 - static SQL
            "order_id TEXT, label_data TEXT, ext TEXT, last_order_data TEXT, queued_at TEXT, status TEXT)"
        )
        conn.execute(
            "CREATE TABLE agent_state("  # noqa: S608 - static SQL
            "key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT INTO printed_orders(order_id, printed_at, last_order_data) VALUES (?, ?, ?)",
            (
                "1",
                "2023-01-01T00:00:00",
                json.dumps(
                    {
                        "name": "Same",
                        "customer": "Same",
                        "products": [{"name": "Prod", "size": "L", "color": "Red"}],
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    ro_path = f"file:{db_file}?mode=ro"

    def ro_sqlite_connect(path, **kwargs):
        if isinstance(path, str) and path.startswith("file:"):
            kwargs.setdefault("uri", True)
        return db_mod.sqlite_connect(path, **kwargs)

    monkeypatch.setattr(app_mod.print_agent, "sqlite_connect", ro_sqlite_connect)
    ro_config = app_mod.print_agent.agent.config.with_updates(db_file=ro_path)
    monkeypatch.setattr(app_mod.print_agent.agent, "config", ro_config)

    caplog.set_level("WARNING")
    resp = client.get("/history")
    assert resp.status_code == 200
    assert any("read-only" in rec.message.lower() for rec in caplog.records)
