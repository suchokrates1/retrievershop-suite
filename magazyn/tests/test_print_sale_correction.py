from decimal import Decimal

from magazyn.db import get_session
from magazyn.domain.inventory import ensure_fulfilled_order_sale
from magazyn.models.orders import Order, OrderProduct, OrderStatusLog
from magazyn.models.products import Product, ProductSize, Sale
from magazyn.services.order_status import add_order_status
from magazyn.services.print_sale_correction import correct_print_stock_deductions


def _seed(db):
    product = Product(category="Szelki", brand="Truelove", series="Front")
    db.add(product)
    db.flush()
    size = ProductSize(
        product_id=product.id,
        size="M",
        quantity=4,
        stock_value=Decimal("200.00"),
        barcode="5900000000001",
    )
    db.add(size)
    db.flush()
    printed = Order(order_id="printed-only")
    packed = Order(order_id="packed-double")
    returned = Order(order_id="returned")
    db.add_all([printed, packed, returned])
    db.flush()
    for order_id in ("printed-only", "packed-double", "returned"):
        db.add(
            OrderProduct(
                order_id=order_id,
                name="Szelki",
                quantity=1,
                ean="5900000000001",
                product_size_id=size.id,
            )
        )
    db.add(OrderStatusLog(order_id="printed-only", status="wydrukowano"))
    db.add(OrderStatusLog(order_id="packed-double", status="spakowano"))
    db.add(OrderStatusLog(order_id="returned", status="zwrot"))
    db.add_all(
        [
            Sale(product_id=product.id, size="M", quantity=1, sale_date="2026-10-23", purchase_cost=Decimal("50.00"), sale_price=Decimal("195.00"), order_id="printed-only"),
            Sale(product_id=product.id, size="M", quantity=1, sale_date="2026-10-23", purchase_cost=Decimal("50.00"), sale_price=Decimal("195.00"), order_id="printed-only"),
            Sale(product_id=product.id, size="M", quantity=1, sale_date="2026-10-23", purchase_cost=Decimal("50.00"), sale_price=Decimal("195.00"), order_id="packed-double"),
            Sale(product_id=product.id, size="M", quantity=1, sale_date="2026-10-23", purchase_cost=Decimal("50.00"), sale_price=Decimal("195.00"), order_id="packed-double"),
            Sale(product_id=product.id, size="M", quantity=1, sale_date="2026-10-23", purchase_cost=Decimal("50.00"), sale_price=Decimal("195.00"), order_id="returned", quantity_returned=1),
        ]
    )
    db.commit()
    return size.id


def test_correction_restores_unpacked_duplicates_and_keeps_one_packed(app):
    with app.app_context():
        with get_session() as db:
            size_id = _seed(db)

        actions = correct_print_stock_deductions()

        with get_session() as db:
            size = db.get(ProductSize, size_id)
            printed_sales = db.query(Sale).filter(Sale.order_id == "printed-only").all()
            packed_sales = db.query(Sale).filter(Sale.order_id == "packed-double").all()
            returned_sales = db.query(Sale).filter(Sale.order_id == "returned").all()

    restored_orders = {row["order_id"] for row in actions}
    assert restored_orders == {"printed-only", "packed-double"}
    assert printed_sales == []
    assert len(packed_sales) == 1
    assert len(returned_sales) == 1
    # 5 sztuk zdjętych, wracają 3 (dwa wydruki + jeden nadmiar ze spakowanego). 4+3=7.
    assert size.quantity == 7
    assert size.stock_value == Decimal("350.00")


def test_pack_deducts_once_and_print_status_does_not(app):
    with app.app_context():
        with get_session() as db:
            product = Product(category="Obroża", brand="Truelove", series="Lumen")
            db.add(product)
            db.flush()
            size = ProductSize(
                product_id=product.id,
                size="M",
                quantity=3,
                stock_value=Decimal("90.00"),
                barcode="5900000000002",
            )
            db.add(size)
            db.flush()
            db.add(Order(order_id="fresh"))
            db.flush()
            db.add(
                OrderProduct(
                    order_id="fresh",
                    name="Obroża",
                    quantity=1,
                    ean="5900000000002",
                    price_brutto=Decimal("60.00"),
                    product_size_id=size.id,
                )
            )
            db.commit()
            size_id = size.id

        with get_session() as db:
            add_order_status(db, "fresh", "wydrukowano", send_email=False)
        with get_session() as db:
            assert db.query(Sale).filter(Sale.order_id == "fresh").count() == 0
            add_order_status(db, "fresh", "spakowano", send_email=False)
        with get_session() as db:
            assert db.query(Sale).filter(Sale.order_id == "fresh").count() == 1
            add_order_status(db, "fresh", "wyslano", send_email=False)
        with get_session() as db:
            assert db.query(Sale).filter(Sale.order_id == "fresh").count() == 1
            size = db.get(ProductSize, size_id)
            assert size.quantity == 2
            assert ensure_fulfilled_order_sale("fresh") is False
