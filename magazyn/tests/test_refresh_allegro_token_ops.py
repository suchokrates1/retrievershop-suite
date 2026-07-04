"""Testy scripts/ops/refresh_allegro_token.py"""
from unittest.mock import patch

import scripts.ops.refresh_allegro_token as refresh_mod


def test_refresh_skips_when_no_refresh_token(app):
    with app.app_context():
        with patch.object(refresh_mod.settings_store, "get", return_value=None):
            assert refresh_mod.refresh() == 0


def test_refresh_calls_api_and_returns_zero(app):
    with app.app_context():
        with patch.object(refresh_mod.settings_store, "reload"):
            with patch.object(refresh_mod.settings_store, "get", return_value="rt-abc"):
                with patch.object(
                    refresh_mod,
                    "refresh_allegro_token",
                    return_value="new-access-token-xyz",
                ) as mock_refresh:
                    assert refresh_mod.refresh() == 0
                    mock_refresh.assert_called_once_with("rt-abc")


def test_refresh_returns_one_on_api_failure(app):
    with app.app_context():
        with patch.object(refresh_mod.settings_store, "reload"):
            with patch.object(refresh_mod.settings_store, "get", return_value="rt-abc"):
                with patch.object(
                    refresh_mod,
                    "refresh_allegro_token",
                    side_effect=RuntimeError("auth failed"),
                ):
                    assert refresh_mod.refresh() == 1
