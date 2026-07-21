"""Testy snapshotu ocen Allegro."""

from __future__ import annotations

from magazyn.services import allegro_ratings_snapshot as mod


def test_fetch_and_save_snapshot(monkeypatch):
    class Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        if url.endswith("/me"):
            return Resp({"id": "47420720", "login": "Retriever_Shop"})
        return Resp(
            {
                "recommended": {"unique": 72, "total": 73},
                "notRecommended": {"unique": 0, "total": 0},
                "recommendedPercentage": "100,0",
                "statistics": {"received": {"total": 73}},
                "user": {"createdAt": "2017-10-29"},
            }
        )

    stored = {}

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod, "_count_orders", lambda: 762)
    monkeypatch.setattr(
        mod.settings_store,
        "get",
        lambda k, default=None: ("tok" if k == "ALLEGRO_ACCESS_TOKEN" else stored.get(k, default)),
    )
    monkeypatch.setattr(
        mod.settings_store,
        "update",
        lambda values: stored.update(values),
    )

    snap = mod.sync_ratings_snapshot(force=True)
    assert snap["login"] == "Retriever_Shop"
    assert snap["recommended_percentage"] == "100,0"
    assert snap["ratings_received_total"] == 73
    assert snap["orders_total"] == 762
    assert snap["orders_rounded_100"] == 700
    assert "allegro.pl/uzytkownik/Retriever_Shop" in snap["profile_url"]
    assert mod.SETTING_KEY in stored


def test_skips_refresh_when_fresh(monkeypatch):
    from datetime import datetime, timezone

    fresh = {
        "login": "Retriever_Shop",
        "recommended_percentage": "100,0",
        "ratings_received_total": 73,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    monkeypatch.setattr(mod, "load_snapshot", lambda: fresh)
    monkeypatch.setattr(
        mod,
        "fetch_ratings_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )
    out = mod.sync_ratings_snapshot(force=False)
    assert out is fresh
