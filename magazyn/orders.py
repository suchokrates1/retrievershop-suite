"""Orders blueprint - view and manage BaseLinker orders."""
import json
from datetime import datetime, timedelta
from typing import Optional

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for
from sqlalchemy import desc, or_

from .auth import login_required
from .db import get_session
from .models import Order, OrderProduct, OrderStatusLog, ProductSize, Product

bp = Blueprint("orders", __name__)


# All valid statuses for the system
VALID_STATUSES = [
    "pobrano",  # Downloaded from BaseLinker
    "niewydrukowano",  # Not printed
    "wydrukowano",  # Printed
    "zdjeto_ze_stanu",  # Stock deducted
    "spakowano",  # Packed
    "przekazano_kurierowi",  # Given to courier
    "odebrano_przez_kuriera",  # Picked up by courier
    "w_drodze",  # In transit
    "awizo",  # Aviso
    "w_punkcie",  # Waiting at pickup point
    "dostarczono",  # Delivered
    "niedostarczono",  # Not delivered
    "zwrot",  # Return
    "zagubiono",  # Lost
    "anulowano",  # Canceled
]


def _unix_to_datetime(timestamp: Optional[int]) -> Optional[datetime]:
    """Convert Unix timestamp to datetime."""
    if timestamp:
        try:
            return datetime.fromtimestamp(timestamp)
        except (ValueError, OSError):
            pass
    return None


def _get_status_display(status: str) -> tuple[str, str]:
    """Return (display text, badge class) for status."""
    STATUS_MAP = {
        "pobrano": ("Pobrano", "bg-light text-dark"),
        "niewydrukowano": ("Niewydrukowano", "bg-secondary"),
        "wydrukowano": ("Wydrukowano", "bg-info"),
        "zdjeto_ze_stanu": ("Zdjęto ze stanu", "bg-info"),
        "spakowano": ("Spakowano", "bg-info"),
        "przekazano_kurierowi": ("Przekazano kurierowi", "bg-primary"),
        "odebrano_przez_kuriera": ("Odebrano przez kuriera", "bg-primary"),
        "w_drodze": ("W drodze", "bg-warning text-dark"),
        "awizo": ("Awizo", "bg-warning text-dark"),
        "w_punkcie": ("Czeka w punkcie", "bg-info"),
        "dostarczono": ("Dostarczono", "bg-success"),
        "niedostarczono": ("Niedostarczono", "bg-danger"),
        "zwrot": ("Zwrot", "bg-danger"),
        "zagubiono": ("Zagubiono", "bg-dark"),
        "anulowano": ("Anulowano", "bg-dark"),
    }
    return STATUS_MAP.get(status, (status, "bg-secondary"))


@bp.route("/orders")
@login_required
def orders_list():
    """Display list of all orders from last 7 days."""
    page = request.args.get("page", 1, type=int)
    per_page = 50
    search = request.args.get("search", "").strip()
    
    # Get orders from last 7 days by default
    week_ago = int((datetime.now() - timedelta(days=7)).timestamp())
    
    with get_session() as db:
        query = db.query(Order).filter(Order.date_add >= week_ago).order_by(desc(Order.date_add))
        
        # Apply search filter
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Order.order_id.ilike(search_pattern),
                    Order.external_order_id.ilike(search_pattern),
                    Order.customer_name.ilike(search_pattern),
                    Order.email.ilike(search_pattern),
                    Order.phone.ilike(search_pattern),
                )
            )
        
        # Pagination
        total = query.count()
        orders = query.offset((page - 1) * per_page).limit(per_page).all()
        
        # Convert timestamps and add latest status
        orders_data = []
        for order in orders:
            # Get latest status
            latest_status = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order.order_id)
                .order_by(desc(OrderStatusLog.timestamp))
                .first()
            )
            
            status_text, status_class = _get_status_display(
                latest_status.status if latest_status else "niewydrukowano"
            )
            
            # Get product summary
            products = db.query(OrderProduct).filter(
                OrderProduct.order_id == order.order_id
            ).all()
            product_summary = ", ".join([
                f"{p.name or 'Produkt'} x{p.quantity}"
                for p in products[:3]
            ])
            if len(products) > 3:
                product_summary += f" (+{len(products) - 3} więcej)"
            
            orders_data.append({
                "order_id": order.order_id,
                "external_order_id": order.external_order_id,
                "shop_order_id": order.shop_order_id,
                "customer_name": order.customer_name,
                "platform": order.platform,
                "date_add": _unix_to_datetime(order.date_add),
                "delivery_method": order.delivery_method,
                "payment_done": order.payment_done,
                "currency": order.currency,
                "status_text": status_text,
                "status_class": status_class,
                "product_summary": product_summary,
                "tracking_number": order.delivery_package_nr,
            })
        
        # Calculate pagination
        total_pages = (total + per_page - 1) // per_page
        
        return render_template(
            "orders_list.html",
            orders=orders_data,
            page=page,
            total_pages=total_pages,
            total=total,
            search=search,
        )


@bp.route("/order/<order_id>")
@login_required
def order_detail(order_id: str):
    """Display detailed view of a single order."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            abort(404)
        
        # Get order products with warehouse links
        products = []
        for op in order.products:
            # Try to link to warehouse via EAN
            warehouse_product = None
            if op.ean:
                ps = db.query(ProductSize).filter(ProductSize.barcode == op.ean).first()
                if ps:
                    warehouse_product = {
                        "id": ps.product_id,
                        "product_size_id": ps.id,
                        "name": ps.product.name if ps.product else None,
                        "color": ps.product.color if ps.product else None,
                        "size": ps.size,
                        "quantity_in_stock": ps.quantity,
                    }
            
            products.append({
                "id": op.id,
                "name": op.name,
                "sku": op.sku,
                "ean": op.ean,
                "quantity": op.quantity,
                "price_brutto": op.price_brutto,
                "attributes": op.attributes,
                "auction_id": op.auction_id,
                "warehouse_product": warehouse_product,
            })
        
        # Get status history
        status_logs = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order_id)
            .order_by(desc(OrderStatusLog.timestamp))
            .all()
        )
        
        status_history = []
        for log in status_logs:
            status_text, status_class = _get_status_display(log.status)
            status_history.append({
                "status": log.status,
                "status_text": status_text,
                "status_class": status_class,
                "timestamp": log.timestamp,
                "tracking_number": log.tracking_number,
                "courier_code": log.courier_code,
                "notes": log.notes,
            })
        
        # Get current status
        current_status = status_history[0] if status_history else {
            "status": "niewydrukowano",
            "status_text": "Niewydrukowano",
            "status_class": "bg-secondary",
        }
        
        return render_template(
            "order_detail.html",
            order=order,
            products=products,
            status_history=status_history,
            current_status=current_status,
            date_add=_unix_to_datetime(order.date_add),
            date_confirmed=_unix_to_datetime(order.date_confirmed),
        )


@bp.route("/order/<order_id>/update_status", methods=["POST"])
@login_required
def update_order_status(order_id: str):
    """Update order status."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            abort(404)
        
        new_status = request.form.get("status")
        tracking_number = request.form.get("tracking_number", "").strip() or None
        courier_code = request.form.get("courier_code", "").strip() or None
        notes = request.form.get("notes", "").strip() or None
        
        if new_status not in VALID_STATUSES:
            flash("Nieprawidłowy status", "error")
            return redirect(url_for(".order_detail", order_id=order_id))
        
        # Create status log entry
        status_log = OrderStatusLog(
            order_id=order_id,
            status=new_status,
            tracking_number=tracking_number,
            courier_code=courier_code,
            notes=notes,
        )
        db.add(status_log)
        
        # Update order tracking info if provided
        if tracking_number:
            order.delivery_package_nr = tracking_number
        if courier_code:
            order.courier_code = courier_code
        
        db.commit()
        
        flash("Status zamówienia zaktualizowany", "success")
        return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/reprint", methods=["POST"])
@login_required
def reprint_label(order_id: str):
    """Reprint shipping label for an order."""
    from . import print_agent
    
    try:
        # Try to get packages and print labels
        packages = print_agent.get_order_packages(order_id)
        printed_any = False
        
        for pkg in packages:
            pid = pkg.get("package_id")
            code = pkg.get("courier_code")
            if not pid or not code:
                continue
            label_data, ext = print_agent.get_label(code, pid)
            if label_data:
                print_agent.print_label(label_data, ext, order_id)
                printed_any = True
        
        if printed_any:
            # Add status log entry
            with get_session() as db:
                add_order_status(db, order_id, "wydrukowano", notes="Reprint etykiety")
                db.commit()
            flash("Etykieta została wysłana do drukarki", "success")
        else:
            flash("Nie znaleziono etykiety do wydruku", "warning")
            
    except Exception as exc:
        flash(f"Błąd drukowania: {exc}", "error")
    
    # Redirect back to wherever the user came from
    referrer = request.referrer
    if referrer and "order" in referrer:
        return redirect(referrer)
    return redirect(url_for(".orders_list"))


def sync_order_from_data(db, order_data: dict) -> Order:
    """
    Create or update Order from BaseLinker data (last_order_data format).
    Called from print_agent when processing orders.
    """
    order_id = str(order_data.get("order_id"))
    
    # Check if order exists
    order = db.query(Order).filter(Order.order_id == order_id).first()
    is_new_order = False
    if not order:
        order = Order(order_id=order_id)
        db.add(order)
        is_new_order = True
    
    # Update all fields from order_data
    order.external_order_id = order_data.get("external_order_id")
    order.shop_order_id = order_data.get("shop_order_id")
    order.customer_name = order_data.get("customer") or order_data.get("delivery_fullname")
    order.email = order_data.get("email")
    order.phone = order_data.get("phone")
    order.user_login = order_data.get("user_login")
    order.platform = order_data.get("platform")
    order.order_source_id = order_data.get("order_source_id")
    order.order_status_id = order_data.get("order_status_id")
    order.confirmed = order_data.get("confirmed", False)
    order.date_add = order_data.get("date_add")
    order.date_confirmed = order_data.get("date_confirmed")
    order.date_in_status = order_data.get("date_in_status")
    order.delivery_method = order_data.get("shipping") or order_data.get("delivery_method")
    order.delivery_method_id = order_data.get("delivery_method_id")
    order.delivery_price = order_data.get("delivery_price")
    order.delivery_fullname = order_data.get("delivery_fullname")
    order.delivery_company = order_data.get("delivery_company")
    order.delivery_address = order_data.get("delivery_address")
    order.delivery_city = order_data.get("delivery_city")
    order.delivery_postcode = order_data.get("delivery_postcode")
    order.delivery_country = order_data.get("delivery_country")
    order.delivery_country_code = order_data.get("delivery_country_code")
    order.delivery_point_id = order_data.get("delivery_point_id")
    order.delivery_point_name = order_data.get("delivery_point_name")
    order.delivery_point_address = order_data.get("delivery_point_address")
    order.delivery_point_postcode = order_data.get("delivery_point_postcode")
    order.delivery_point_city = order_data.get("delivery_point_city")
    order.invoice_fullname = order_data.get("invoice_fullname")
    order.invoice_company = order_data.get("invoice_company")
    order.invoice_nip = order_data.get("invoice_nip")
    order.invoice_address = order_data.get("invoice_address")
    order.invoice_city = order_data.get("invoice_city")
    order.invoice_postcode = order_data.get("invoice_postcode")
    order.invoice_country = order_data.get("invoice_country")
    order.want_invoice = order_data.get("want_invoice") == "1"
    order.currency = order_data.get("currency", "PLN")
    order.payment_method = order_data.get("payment_method")
    order.payment_method_cod = order_data.get("payment_method_cod") == "1"
    order.payment_done = order_data.get("payment_done")
    order.user_comments = order_data.get("user_comments")
    order.admin_comments = order_data.get("admin_comments")
    order.courier_code = order_data.get("courier_code")
    order.delivery_package_module = order_data.get("delivery_package_module")
    order.delivery_package_nr = order_data.get("delivery_package_nr")
    
    # Store raw products JSON
    products_list = order_data.get("products", [])
    order.products_json = json.dumps(products_list) if products_list else None
    
    # Sync order products
    # First, remove existing products for this order
    db.query(OrderProduct).filter(OrderProduct.order_id == order_id).delete()
    
    for prod in products_list:
        ean = prod.get("ean", "").strip() or None
        
        # Try to link to warehouse via EAN
        product_size_id = None
        if ean:
            ps = db.query(ProductSize).filter(ProductSize.barcode == ean).first()
            if ps:
                product_size_id = ps.id
        
        order_product = OrderProduct(
            order_id=order_id,
            order_product_id=prod.get("order_product_id"),
            product_id=prod.get("product_id"),
            variant_id=prod.get("variant_id"),
            sku=prod.get("sku"),
            ean=ean,
            name=prod.get("name"),
            quantity=prod.get("quantity", 1),
            price_brutto=prod.get("price_brutto"),
            auction_id=prod.get("auction_id"),
            attributes=prod.get("attributes"),
            location=prod.get("location"),
            product_size_id=product_size_id,
        )
        db.add(order_product)
    
    # Add "pobrano" status for new orders
    if is_new_order:
        add_order_status(db, order_id, "pobrano", notes="Pobrano z BaseLinker")
    
    return order


def add_order_status(db, order_id: str, status: str, **kwargs) -> OrderStatusLog:
    """Add a status log entry for an order."""
    log = OrderStatusLog(
        order_id=order_id,
        status=status,
        tracking_number=kwargs.get("tracking_number"),
        courier_code=kwargs.get("courier_code"),
        notes=kwargs.get("notes"),
    )
    db.add(log)
    return log
