from types import SimpleNamespace

from magazyn.domain.order_platform import is_allegro_order, is_manual_order, is_woo_order


def test_order_platform_helpers():
    assert is_allegro_order("allegro_abc")
    assert is_woo_order("woo_3415")
    assert is_manual_order("manual_1")
    assert not is_allegro_order("woo_1")
    assert not is_woo_order("allegro_1")
    assert is_allegro_order(SimpleNamespace(order_id="allegro_x"))
    assert is_woo_order(SimpleNamespace(order_id="woo_9"))
