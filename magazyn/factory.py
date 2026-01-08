"""Application factory for the magazyn package."""

from __future__ import annotations

import atexit
from typing import Optional, Mapping, Any

from flask import Flask

from .config import settings
from .constants import ALL_SIZES
from .products import bp as products_bp
from .history import bp as history_bp
from .sales import bp as sales_bp
from .shipping import bp as shipping_bp
from .allegro import bp as allegro_bp
from .api_scraper import api_scraper_bp
from .orders import bp as orders_bp
from . import print_agent
from .app import bp as main_bp, start_print_agent, ensure_db_initialized
from .discussions import bp as discussions_bp
from .diagnostics import bp as diagnostics_bp
from .socketio_extension import socketio
from .csrf_extension import csrf
from .db import configure_engine, create_default_user_if_needed, Base, engine
from . import order_sync_scheduler

_shutdown_registered = False


def _register_shutdown_hook() -> None:
    global _shutdown_registered
    if _shutdown_registered:
        return
    atexit.register(print_agent.stop_agent_thread)
    atexit.register(order_sync_scheduler.stop_sync_scheduler)
    _shutdown_registered = True


def create_app(config: Optional[Mapping[str, Any]] = None) -> Flask:
    """Create and configure a :class:`Flask` application instance."""

    app = Flask(__name__)
    app.secret_key = settings.SECRET_KEY

    if config:
        app.config.update(config)

    configure_engine(settings.DB_PATH)

    csrf.init_app(app)
    csrf.exempt(api_scraper_bp)  # Exempt scraper API from CSRF protection
    app.jinja_env.globals["ALL_SIZES"] = ALL_SIZES

    app.register_blueprint(main_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(shipping_bp)
    app.register_blueprint(allegro_bp)
    app.register_blueprint(api_scraper_bp)
    app.register_blueprint(diagnostics_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(discussions_bp)

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
        Base.metadata.create_all(engine)
        create_default_user_if_needed(app)

    start_print_agent(app)
    
    # Start automatic order sync scheduler (every 1 hour)
    order_sync_scheduler.start_sync_scheduler(app)

    _register_shutdown_hook()

    # Initialize SocketIO with gevent (matches gunicorn worker class)
    socketio.init_app(
        app, 
        cors_allowed_origins="*", 
        async_mode='gevent',
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
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.socket.io https://static.cloudflareinsights.com; "
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
