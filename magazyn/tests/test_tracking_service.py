from magazyn.services.tracking import get_tracking_url


def test_get_tracking_url_inpost_encodes_number():
    url = get_tracking_url("INPOST", None, "ABC 123")

    assert url == "https://inpost.pl/sledzenie-przesylek?number=ABC+123"


def test_get_tracking_url_dpd_from_delivery_method():
    url = get_tracking_url(None, None, "123456", "Allegro Kurier DPD")

    assert url == "https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1=123456"


def test_get_tracking_url_returns_none_for_allegro_only_tracking():
    assert get_tracking_url(None, None, "XYZ", "Allegro One Box") is None


def test_get_tracking_url_returns_none_without_number():
    assert get_tracking_url("INPOST", None, None) is None