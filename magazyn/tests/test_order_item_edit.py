"""Testy edycji wariantu (kolor/rozmiar) pozycji zamowienia."""

from decimal import Decimal
from unittest.mock import patch

from magazyn.db import get_session
from magazyn.models.orders import Order, OrderProduct, OrderStatusLog
from magazyn.models.products import Product, ProductSize, Sale
from magazyn.services.order_item_edit import edit_order_item_variant, list_variant_options
from magazyn.services.order_sync import sync_order_from_data


def _seed_security_variants(db):
    orange = Product(
        category="Szelki",
        brand="Truelove",
        series="Security",
        color="pomaranczowe",
    )
    black = Product(
        category="Szelki",
        brand="Truelove",
        series="Security",
        color="czarne",
    )
    other = Product(
        category="Szelki",
        brand="Truelove",
        series="Tropical",
        color="turkusowe",
    )
    db.add_all([orange, black, other])
    db.flush()
    orange_l = ProductSize(
        product_id=orange.id,
        size="L",
        quantity=0,
        barcode="EAN-ORANGE-L",
        stock_value=Decimal("0"),
    )
    black_l = ProductSize(
        product_id=black.id,
        size="L",
        quantity=5,
        barcode="EAN-BLACK-L",
        stock_value=Decimal("150.00"),
    )
    tropical_l = ProductSize(
        product_id=other.id,
        size="L",
        quantity=3,
        barcode="EAN-TROP-L",
        stock_value=Decimal("90.00"),
    )
    db.add_all([orange_l, black_l, tropical_l])
    db.flush()
    return orange, black, other, orange_l, black_l, tropical_l


def test_edit_rejects_different_series(app):
    order_id = "edit_wrong_series"
    with app.app_context():
        with get_session() as db:
            _, _, _, orange_l, _, tropical_l = _seed_security_variants(db)
            db.add(Order(order_id=order_id, platform="allegro"))
            op = OrderProduct(
                order_id=order_id,
                name="Szelki Security L pomaranczowe",
                quantity=1,
                price_brutto=Decimal("120.00"),
                product_size_id=orange_l.id,
                ean=orange_l.barcode,
            )
            db.add(op)
            db.add(OrderStatusLog(order_id=order_id, status="pobrano"))
            db.commit()
            op_id = op.id
            tropical_id = tropical_l.id

        result = edit_order_item_variant(
            order_id,
            op_id,
            tropical_id,
            restore_previous_stock=False,
        )
        assert result.category == "error"
        assert "rodzinie" in result.message


def test_edit_swap_color_without_restore_keeps_zero(app):
    order_id = "edit_no_restore"
    with app.app_context():
        with get_session() as db:
            _, _, _, orange_l, black_l, _ = _seed_security_variants(db)
            db.add(Order(order_id=order_id, platform="allegro"))
            op = OrderProduct(
                order_id=order_id,
                name="Szelki Security L pomaranczowe",
                quantity=1,
                price_brutto=Decimal("120.00"),
                product_size_id=orange_l.id,
                ean=orange_l.barcode,
            )
            db.add(op)
            db.add(OrderStatusLog(order_id=order_id, status="wydrukowano"))
            db.add(
                Sale(
                    product_id=orange_l.product_id,
                    size="L",
                    quantity=1,
                    sale_date="2026-07-21",
                    purchase_cost=Decimal("40.00"),
                    sale_price=Decimal("120.00"),
                    order_id=order_id,
                )
            )
            db.commit()
            op_id = op.id
            orange_id = orange_l.id
            black_id = black_l.id

        with patch(
            "magazyn.services.invoice_service.generate_variant_correction_invoice",
            return_value={"success": True, "skipped": True, "invoice_number": None, "errors": []},
        ):
            result = edit_order_item_variant(
                order_id,
                op_id,
                black_id,
                restore_previous_stock=False,
            )

        assert result.category in ("success", "warning")
        assert result.details["restored_previous"] is False
        assert result.details["consumed_new"] is True

        with get_session() as db:
            orange = db.query(ProductSize).filter(ProductSize.id == orange_id).first()
            black = db.query(ProductSize).filter(ProductSize.id == black_id).first()
            op = db.query(OrderProduct).filter(OrderProduct.id == op_id).first()
            order = db.query(Order).filter(Order.order_id == order_id).first()
            assert orange.quantity == 0
            assert black.quantity == 4
            assert op.product_size_id == black_id
            assert "czarne" in (op.name or "").lower() or "czarn" in (op.name or "").lower()
            assert order.items_locally_edited is True


def test_edit_with_restore_returns_old_stock(app):
    order_id = "edit_with_restore"
    with app.app_context():
        with get_session() as db:
            _, _, _, orange_l, black_l, _ = _seed_security_variants(db)
            orange_l.quantity = 0
            orange_l.stock_value = Decimal("0")
            db.add(Order(order_id=order_id, platform="allegro"))
            op = OrderProduct(
                order_id=order_id,
                name="Szelki Security L pomaranczowe",
                quantity=1,
                price_brutto=Decimal("120.00"),
                product_size_id=orange_l.id,
                ean=orange_l.barcode,
            )
            db.add(op)
            db.add(OrderStatusLog(order_id=order_id, status="wydrukowano"))
            db.add(
                Sale(
                    product_id=orange_l.product_id,
                    size="L",
                    quantity=1,
                    sale_date="2026-07-21",
                    purchase_cost=Decimal("40.00"),
                    sale_price=Decimal("120.00"),
                    order_id=order_id,
                )
            )
            db.commit()
            op_id = op.id
            orange_id = orange_l.id
            black_id = black_l.id

        with patch(
            "magazyn.services.invoice_service.generate_variant_correction_invoice",
            return_value={"success": True, "skipped": True, "invoice_number": None, "errors": []},
        ):
            result = edit_order_item_variant(
                order_id,
                op_id,
                black_id,
                restore_previous_stock=True,
            )

        assert result.details["restored_previous"] is True
        with get_session() as db:
            orange = db.query(ProductSize).filter(ProductSize.id == orange_id).first()
            assert orange.quantity == 1


def test_sync_skips_products_when_locally_edited(app):
    order_id = "edit_sync_lock"
    with app.app_context():
        with get_session() as db:
            _, _, _, orange_l, black_l, _ = _seed_security_variants(db)
            order = Order(
                order_id=order_id,
                platform="allegro",
                external_order_id="cf-lock",
                items_locally_edited=True,
            )
            db.add(order)
            op = OrderProduct(
                order_id=order_id,
                name="Lokalnie zmienione czarne",
                quantity=1,
                price_brutto=Decimal("120.00"),
                product_size_id=black_l.id,
                ean=black_l.barcode,
            )
            db.add(op)
            db.commit()
            op_id = op.id
            locked_ean = black_l.barcode

        with get_session() as db:
            sync_order_from_data(
                db,
                {
                    "order_id": order_id,
                    "external_order_id": "cf-lock",
                    "platform": "allegro",
                    "payment_done": 120,
                    "products": [
                        {
                            "name": "Szelki Security L pomaranczowe",
                            "ean": "EAN-ORANGE-L",
                            "quantity": 1,
                            "price_brutto": 120,
                        }
                    ],
                },
            )
            db.commit()

        with get_session() as db:
            products = db.query(OrderProduct).filter(OrderProduct.order_id == order_id).all()
            assert len(products) == 1
            assert products[0].id == op_id
            assert products[0].ean == locked_ean


def test_variant_correction_passes_new_name(app):
    order_id = "edit_corr_name"
    with app.app_context():
        with get_session() as db:
            _, _, _, orange_l, black_l, _ = _seed_security_variants(db)
            db.add(
                Order(
                    order_id=order_id,
                    platform="allegro",
                    wfirma_invoice_id=123,
                )
            )
            op = OrderProduct(
                order_id=order_id,
                name="Szelki Security L pomaranczowe",
                quantity=1,
                price_brutto=Decimal("120.00"),
                product_size_id=orange_l.id,
            )
            db.add(op)
            db.add(OrderStatusLog(order_id=order_id, status="pobrano"))
            db.commit()
            op_id = op.id
            black_id = black_l.id

        with patch(
            "magazyn.services.invoice_service.generate_variant_correction_invoice"
        ) as corr_mock:
            corr_mock.return_value = {
                "success": True,
                "skipped": False,
                "invoice_number": "KOR/1",
                "errors": [],
            }
            result = edit_order_item_variant(
                order_id,
                op_id,
                black_id,
                restore_previous_stock=False,
            )

        assert corr_mock.called
        kwargs = corr_mock.call_args.kwargs
        assert kwargs["order_id"] == order_id
        assert "pomarancz" in kwargs["old_name"].lower() or "Security" in kwargs["old_name"]
        assert result.details.get("correction_number") == "KOR/1"


def test_list_variant_options_same_family(app):
    order_id = "edit_options"
    with app.app_context():
        with get_session() as db:
            _, _, _, orange_l, black_l, tropical_l = _seed_security_variants(db)
            db.add(Order(order_id=order_id, platform="allegro"))
            op = OrderProduct(
                order_id=order_id,
                name="Szelki Security L pomaranczowe",
                quantity=1,
                product_size_id=orange_l.id,
            )
            db.add(op)
            db.add(OrderStatusLog(order_id=order_id, status="pobrano"))
            db.commit()
            op_id = op.id
            black_id = black_l.id
            tropical_id = tropical_l.id

        data = list_variant_options(order_id, op_id)
        assert data["ok"] is True
        ids = {v["product_size_id"] for v in data["variants"]}
        assert black_id in ids
        assert tropical_id not in ids
