"""Application factory for the magazyn package."""

from __future__ import annotations

import atexit
import os
import sys
from typing import Optional, Mapping, Any

from flask import Flask

from .config import settings
from .constants import ALL_SIZES
from .products import bp as products_bp
from .history import bp as history_bp
from .sales import bp as sales_bp
from .allegro import bp as allegro_bp
from .orders import bp as orders_bp
from . import print_agent
from .app import bp as main_bp, start_print_agent, ensure_db_initialized
from .discussions import bp as discussions_bp
from .diagnostics import bp as diagnostics_bp
from .integration_proxy import bp as integration_proxy_bp
from .blueprints import scanning_bp, stocktake_bp, customer_order_bp
from .price_reports import bp as price_reports_bp
from .socketio_extension import socketio
from .csrf_extension import csrf
from .db import configure_engine, create_default_user_if_needed, Base, engine
from .settings_store import settings_store
from . import order_sync_scheduler
from . import promo_scheduler

_shutdown_registered = False
_app_instance: Optional[Flask] = None


def _register_shutdown_hook() -> None:
    global _shutdown_registered
    if _shutdown_registered:
        return
    atexit.register(print_agent.stop_agent_thread)
    atexit.register(order_sync_scheduler.stop_sync_scheduler)
    atexit.register(promo_scheduler.stop_promo_scheduler)
    _shutdown_registered = True


def _start_order_sync_scheduler() -> None:
    """Start order sync scheduler - called from gunicorn post_worker_init hook."""
    global _app_instance
    if _app_instance is not None:
        order_sync_scheduler.start_sync_scheduler(_app_instance)


def _start_promo_scheduler() -> None:
    """Start promo scheduler - called from gunicorn post_worker_init hook."""
    global _app_instance
    if _app_instance is not None:
        promo_scheduler.start_promo_scheduler(_app_instance)


def create_app(config: Optional[Mapping[str, Any]] = None) -> Flask:
    """Create and configure a :class:`Flask` application instance."""

    app = Flask(__name__)
    app.secret_key = settings.SECRET_KEY
    
    # Configure CSRF protection
    app.config['WTF_CSRF_TIME_LIMIT'] = None  # Disable CSRF token expiration

    if config:
        app.config.update(config)

    configure_engine(settings.DB_PATH)
    # Po skonfigurowaniu engine (PostgreSQL) przeladuj settings_store
    # zeby odczytac aktualne wartosci z wlasciwej bazy danych
    # (poczatkowy load mogl uzyc SQLite fallback gdy engine=None)
    settings_store.reload()

    csrf.init_app(app)
    app.jinja_env.globals["ALL_SIZES"] = ALL_SIZES
    
    # Register custom template filters
    @app.template_filter('parse_datetime')
    def parse_datetime_filter(s):
        """Parse ISO 8601 datetime string to Python datetime."""
        from datetime import datetime
        if not s:
            return None
        try:
            # Handle ISO 8601 with timezone (e.g., "2024-01-15T10:30:00Z")
            return datetime.fromisoformat(s.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    @app.template_filter('format_datetime')
    def format_datetime_filter(dt, format='%Y-%m-%d %H:%M'):
        """Format datetime object to string."""
        if not dt:
            return ''
        try:
            return dt.strftime(format)
        except (AttributeError, ValueError):
            return str(dt)

    app.register_blueprint(main_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(allegro_bp)
    app.register_blueprint(diagnostics_bp)
    app.register_blueprint(integration_proxy_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(discussions_bp)
    app.register_blueprint(scanning_bp)
    app.register_blueprint(stocktake_bp)
    app.register_blueprint(price_reports_bp)
    app.register_blueprint(customer_order_bp)

    for rule in list(app.url_map.iter_rules()):
        if rule.endpoint.startswith("main."):
            simple_endpoint = rule.endpoint.split(".", 1)[1]
            app.view_functions[simple_endpoint] = app.view_functions[rule.endpoint]
            app.url_map._rules_by_endpoint.setdefault(simple_endpoint, []).append(
                rule
            )

    with app.app_context():
        ensure_db_initialized(app)
        # Note: Alembic migrations are now run via entrypoint.sh before gunicorn starts
        # This prevents multiple workers from trying to run migrations simultaneously
        # Base.metadata.create_all(engine)  # Removed: use Alembic migrations only
        create_default_user_if_needed(app)

    start_print_agent(app)
    
    # Start token refresher only in dev mode (flask run / wsgi __main__).
    # In production gunicorn.conf.py starts it in exactly one worker via file lock.
    _is_gunicorn = "gunicorn" in sys.modules
    if not _is_gunicorn:
        from .allegro_token_refresher import token_refresher
        try:
            token_refresher.start()
        except Exception as exc:
            app.logger.error("Failed to start Allegro token refresher: %s", exc)

    # Store app instance for scheduler initialization from gunicorn hook
    global _app_instance
    _app_instance = app
    
    # Note: Order sync scheduler is started by gunicorn's post_worker_init hook
    # See gunicorn.conf.py - this ensures only ONE scheduler runs across all workers

    _register_shutdown_hook()

    # Initialize SocketIO with threading (matches gunicorn sync worker class)
    socketio.init_app(
        app, 
        cors_allowed_origins="*", 
        async_mode='threading',
        manage_session=False,  # Don't manage sessions (Flask handles this)
        engineio_logger=False,  # Reduce log spam
        logger=False
    )

    @app.after_request
    def apply_security_headers(response):
        """Attach security headers to every response."""

        csp = (
            "default-src 'self'; "
            "img-src 'self' https://retrievershop.pl data: blob:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdn.socket.io https://cdn.tailwindcss.com https://static.cloudflareinsights.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net data:; "
            "connect-src 'self' https://cloudflareinsights.com https://cdn.jsdelivr.net https://cdn.socket.io wss: ws:; "
            "object-src 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'self'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Initialize the application database."""
        with app.app_context():
            ensure_db_initialized(app)

    return app
