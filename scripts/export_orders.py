"""Eksport zamowien z bazy do JSON - do analizy."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from magazyn.factory import create_app

app = create_app()
with app.app_context():
    from magazyn.db import get_session
    from magazyn.models import Order, OrderProduct

    with get_session() as db:
        orders = db.query(Order).all()
        print(f"Total orders: {len(orders)}", file=sys.stderr)

        data = []
        for o in orders:
            prods = db.query(OrderProduct).filter_by(order_id=o.order_id).all()
            products = []
            for p in prods:
                products.append({
                    "name": p.name,
                    "sku": p.sku,
                    "ean": p.ean,
                    "quantity": p.quantity,
                    "price_brutto": float(p.price_brutto) if p.price_brutto else 0,
                    "product_size_id": p.product_size_id,
                    "auction_id": p.auction_id,
                })
            data.append({
                "order_id": o.order_id,
                "external_order_id": o.external_order_id,
                "shop_order_id": o.shop_order_id,
                "customer_name": o.customer_name,
                "email": o.email,
                "phone": o.phone,
                "user_login": o.user_login,
                "platform": o.platform,
                "order_status_id": o.order_status_id,
                "confirmed": o.confirmed,
                "date_add": o.date_add,
                "date_confirmed": o.date_confirmed,
                "delivery_method": o.delivery_method,
                "delivery_method_id": o.delivery_method_id,
                "delivery_price": float(o.delivery_price) if o.delivery_price else 0,
                "delivery_city": o.delivery_city,
                "delivery_postcode": o.delivery_postcode,
                "delivery_country_code": o.delivery_country_code,
                "delivery_point_name": o.delivery_point_name,
                "delivery_package_module": o.delivery_package_module,
                "delivery_package_nr": o.delivery_package_nr,
                "currency": o.currency,
                "payment_method": o.payment_method,
                "payment_done": float(o.payment_done) if o.payment_done else 0,
                "want_invoice": o.want_invoice,
                "invoice_company": o.invoice_company,
                "invoice_nip": o.invoice_nip,
                "products": products,
            })
        print(json.dumps(data, ensure_ascii=False, default=str))
