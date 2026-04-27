"""Testy dla magazyn.allegro_api.carriers."""

from unittest.mock import patch, MagicMock

from magazyn.allegro_api.carriers import (
    fetch_carriers,
    resolve_carrier_id,
    invalidate_carriers_cache,
    DELIVERY_METHOD_TO_CARRIER,
    TRACKING_TO_INTERNAL,
)


# --------------- helpers ---------------

def _mock_response(json_data):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = 200
    return resp


# --------------- fetch_carriers ---------------

@patch("magazyn.allegro_api.carriers._call_with_refresh")
def test_fetch_carriers(mock_call):
    invalidate_carriers_cache()
    carriers = [
        {"id": "INPOST", "name": "InPost"},
        {"id": "DPD", "name": "DPD"},
    ]
    mock_call.return_value = _mock_response({"carriers": carriers})

    result = fetch_carriers()

    assert result == carriers
    mock_call.assert_called_once()


@patch("magazyn.allegro_api.carriers._call_with_refresh")
def test_fetch_carriers_cached(mock_call):
    invalidate_carriers_cache()
    carriers = [{"id": "INPOST", "name": "InPost"}]
    mock_call.return_value = _mock_response({"carriers": carriers})

    result1 = fetch_carriers()
    result2 = fetch_carriers()

    assert result1 == result2
    assert mock_call.call_count == 1


@patch("magazyn.allegro_api.carriers._call_with_refresh")
def test_fetch_carriers_list_fallback(mock_call):
    invalidate_carriers_cache()
    carriers = [{"id": "DHL", "name": "DHL"}]
    mock_call.return_value = _mock_response(carriers)

    result = fetch_carriers()

    assert result == carriers


# --------------- resolve_carrier_id ---------------

def test_resolve_inpost_paczkomaty():
    assert resolve_carrier_id("Allegro Paczkomaty InPost 24/7") == "INPOST"


def test_resolve_inpost_kurier():
    assert resolve_carrier_id("Allegro Kurier InPost") == "INPOST"


def test_resolve_dpd():
    assert resolve_carrier_id("Allegro Kurier DPD") == "DPD"


def test_resolve_dhl():
    assert resolve_carrier_id("Allegro Kurier DHL") == "DHL"


def test_resolve_ups():
    assert resolve_carrier_id("Allegro Kurier UPS") == "UPS"


def test_resolve_gls():
    assert resolve_carrier_id("Allegro Kurier GLS") == "GLS"


def test_resolve_poczta_polska():
    assert resolve_carrier_id("Allegro Kurier Pocztex") == "POCZTA_POLSKA"


def test_resolve_one_box():
    assert resolve_carrier_id("Allegro One Box") == "ALLEGRO"


def test_resolve_one_punkt():
    assert resolve_carrier_id("Allegro One Punkt") == "ALLEGRO"


def test_resolve_orlen():
    assert resolve_carrier_id("Allegro Automat Orlen Paczka") == "ORLEN_PACZKA"


def test_resolve_fedex():
    assert resolve_carrier_id("Allegro Kurier FedEx") == "FEDEX"


def test_resolve_unknown():
    assert resolve_carrier_id("Odbiór osobisty") == "OTHER"


def test_resolve_empty():
    assert resolve_carrier_id("") == "OTHER"


def test_resolve_none():
    assert resolve_carrier_id(None) == "OTHER"


def test_resolve_case_insensitive():
    assert resolve_carrier_id("allegro paczkomaty inpost") == "INPOST"
    assert resolve_carrier_id("ALLEGRO KURIER DPD") == "DPD"


# --------------- resolve_carrier_id keyword fallback ---------------

def test_resolve_keyword_inpost():
    """Fallback na slowo kluczowe gdy brak dokladnego dopasowania."""
    assert resolve_carrier_id("Przesylka InPost express") == "INPOST"


def test_resolve_keyword_dhl():
    assert resolve_carrier_id("DHL dostawa 24h") == "DHL"


# --------------- stale ---------------

def test_tracking_to_internal_keys():
    assert "DELIVERED" in TRACKING_TO_INTERNAL
    assert "IN_TRANSIT" in TRACKING_TO_INTERNAL
    assert TRACKING_TO_INTERNAL["DELIVERED"] == "dostarczono"


def test_delivery_method_map():
    assert "allegro kurier dpd" in DELIVERY_METHOD_TO_CARRIER
    assert DELIVERY_METHOD_TO_CARRIER["allegro kurier dpd"] == "DPD"
