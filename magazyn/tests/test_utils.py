import json
import sqlite3
import pytest


def get_bl():
    import importlib
    import magazyn.print_agent as bl
    return importlib.reload(bl)


def test_shorten_product_name():
    bl = get_bl()
    assert bl.shorten_product_name("one two three four") == "one three four"
    assert bl.shorten_product_name("one two") == "one two"


def test_is_quiet_time(monkeypatch):
    bl = get_bl()
    import datetime as dt

    class DummyDateTime:
        current = dt.datetime(2023, 1, 1, 0, 0)
        seen_tz = None

        @classmethod
        def now(cls, tz=None):
            cls.seen_tz = tz
            return cls.current

    monkeypatch.setattr(bl, "ZoneInfo", lambda tz: f"zone-{tz}")

    monkeypatch.setattr(bl, "datetime", DummyDateTime)
    monkeypatch.setattr(bl, "QUIET_HOURS_START", bl.parse_time_str("10:00"))
    monkeypatch.setattr(bl, "QUIET_HOURS_END", bl.parse_time_str("22:00"))
    monkeypatch.setattr(bl, "TIMEZONE", "Test/Zone")

    DummyDateTime.current = dt.datetime(2023, 1, 1, 11, 0)
    assert bl.is_quiet_time() is True
    assert DummyDateTime.seen_tz == "zone-Test/Zone"

    DummyDateTime.current = dt.datetime(2023, 1, 1, 23, 0)
    assert bl.is_quiet_time() is False

    monkeypatch.setattr(bl, "QUIET_HOURS_START", bl.parse_time_str("22:00"))
    monkeypatch.setattr(bl, "QUIET_HOURS_END", bl.parse_time_str("08:00"))

    DummyDateTime.current = dt.datetime(2023, 1, 1, 23, 0)
    assert bl.is_quiet_time() is True

    DummyDateTime.current = dt.datetime(2023, 1, 1, 7, 0)
    assert bl.is_quiet_time() is True

    DummyDateTime.current = dt.datetime(2023, 1, 1, 12, 0)
    assert bl.is_quiet_time() is False


def test_mark_and_load_printed(tmp_path, monkeypatch):
    bl = get_bl()
    db = tmp_path / "test.db"
    monkeypatch.setattr(bl, "DB_FILE", str(db))
    bl.ensure_db()
    bl.mark_as_printed("abc", {"name": "P", "color": "C", "size": "S"})
    orders = bl.load_printed_orders()
    assert any(o["order_id"] == "abc" for o in orders)
    assert orders[0]["last_order_data"]["name"] == "P"


def test_mark_as_printed_deduplicates(tmp_path, monkeypatch):
    bl = get_bl()
    db = tmp_path / "test_dupes.db"
    monkeypatch.setattr(bl, "DB_FILE", str(db))
    bl.ensure_db()

    import datetime as dt

    class DummyDateTime(dt.datetime):
        ts = dt.datetime.fromisoformat("2023-01-01T00:00:00")

        @classmethod
        def now(cls, tz=None):
            return cls.ts

    monkeypatch.setattr(bl, "datetime", DummyDateTime)

    bl.mark_as_printed("xyz")
    first = {o["order_id"]: o["printed_at"] for o in bl.load_printed_orders()}[
        "xyz"
    ]

    DummyDateTime.ts = dt.datetime.fromisoformat("2024-02-02T00:00:00")
    bl.mark_as_printed("xyz")
    second = {
        o["order_id"]: o["printed_at"] for o in bl.load_printed_orders()
    }["xyz"]

    assert first == second


def test_load_printed_orders_sorted(tmp_path, monkeypatch):
    bl = get_bl()
    db = tmp_path / "sorted.db"
    monkeypatch.setattr(bl, "DB_FILE", str(db))
    bl.ensure_db()

    import datetime as dt

    class DummyDateTime(dt.datetime):
        ts = dt.datetime.fromisoformat("2023-01-01T00:00:00")

        @classmethod
        def now(cls, tz=None):
            return cls.ts

    monkeypatch.setattr(bl, "datetime", DummyDateTime)

    bl.mark_as_printed("1")
    DummyDateTime.ts = dt.datetime.fromisoformat("2023-01-02T00:00:00")
    bl.mark_as_printed("2")

    orders = bl.load_printed_orders()
    ids = [o["order_id"] for o in orders]
    assert ids == ["2", "1"]


def test_queue_roundtrip(tmp_path, monkeypatch):
    bl = get_bl()
    db = tmp_path / "queue.db"
    monkeypatch.setattr(bl, "DB_FILE", str(db))
    bl.ensure_db()
    item = {
        "order_id": "1",
        "label_data": "xxx",
        "ext": "pdf",
        "last_order_data": {"a": 1},
    }
    bl.save_queue([item])
    loaded = bl.load_queue()
    assert len(loaded) == 1
    assert loaded[0]["order_id"] == item["order_id"]
    assert loaded[0]["label_data"] == item["label_data"]
    assert loaded[0]["ext"] == item["ext"]
    assert loaded[0]["last_order_data"] == item["last_order_data"]


def test_validate_env_missing_api_token(monkeypatch):
    bl = get_bl()
    monkeypatch.setattr(bl, "API_TOKEN", "")
    monkeypatch.setattr(bl, "PAGE_ACCESS_TOKEN", "x")
    monkeypatch.setattr(bl, "RECIPIENT_ID", "x")
    with pytest.raises(bl.ConfigError):
        bl.validate_env()


def test_load_queue_handles_corrupted_json(tmp_path, monkeypatch):
    bl = get_bl()
    db = tmp_path / "queue_bad.db"
    monkeypatch.setattr(bl, "DB_FILE", str(db))
    bl.ensure_db()
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO label_queue(order_id, label_data, ext, last_order_data) VALUES (?,?,?,?)",
        ("1", "xxx", "pdf", "{bad json"),
    )
    conn.commit()
    conn.close()
    items = bl.load_queue()
    assert items[0]["last_order_data"] == {}


def test_call_api_handles_http_error(monkeypatch):
    bl = get_bl()
    class DummyResp:
        status_code = 500

        def json(self):
            return {"error": "x"}

        def raise_for_status(self):
            raise bl.requests.HTTPError("500")

    monkeypatch.setattr(bl.requests, "post", lambda *a, **k: DummyResp())

    result = bl.call_api("dummy")
    assert result == {}


def test_ensure_db_migrates_wrong_name(tmp_path, monkeypatch):
    bl = get_bl()
    db = tmp_path / "mig.db"
    monkeypatch.setattr(bl, "DB_FILE", str(db))
    bl.ensure_db()
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    bad = {
        "name": "John Doe",
        "customer": "John Doe",
        "products": [{"name": "Widget Blue XL"}],
    }
    cur.execute(
        "INSERT INTO printed_orders(order_id, printed_at, last_order_data) VALUES (?,?,?)",
        ("1", "2023-01-01T00:00:00", json.dumps(bad)),
    )
    conn.commit()
    conn.close()
    bl.ensure_db()
    orders = bl.load_printed_orders()
    data = orders[0]["last_order_data"]
    assert data["name"] == "Widget"
    assert data["color"] == "Blue"
    assert data["size"] == "XL"
