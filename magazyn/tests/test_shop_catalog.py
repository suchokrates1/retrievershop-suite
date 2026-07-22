from magazyn.services.shop_catalog import get_shop_bestsellers, get_shop_latest_delivery


def test_shop_bestsellers_shape(app_mod):
    data = get_shop_bestsellers(limit=4, days=90)
    assert data["ok"] is True
    assert data["type"] == "bestsellers"
    assert isinstance(data["items"], list)
    for item in data["items"]:
        assert item.get("woo_product_id")
        assert item.get("product_id")
        assert "quantity" in item


def test_shop_latest_delivery_shape(app_mod):
    data = get_shop_latest_delivery(limit=4)
    assert data["ok"] is True
    assert data["type"] == "latest_delivery"
    assert isinstance(data["items"], list)
    for item in data["items"]:
        assert item.get("woo_product_id")
        assert item.get("product_id")
