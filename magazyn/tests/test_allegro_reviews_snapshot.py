"""Unit-ish tests for Allegro reviews snapshot helpers."""

from __future__ import annotations

from magazyn.services import allegro_reviews_snapshot as mod


def test_mask_login_client_prefix():
    assert mod._mask_login("Client:12345") == "Klient Allegro"
    assert mod._mask_login("Tom_Mur") == "Tom_Mur"


def test_stars_from_rates_avg():
    assert mod._stars_from_rates({"delivery": 5, "service": 4}) == 4.5
    assert mod._stars_from_rates({}) == 5.0


def test_normalize_comment_strips():
    assert mod._normalize_comment("  a   b  ") == "a b"
