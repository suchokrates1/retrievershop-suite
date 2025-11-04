"""Application factory for the magazyn package."""

from __future__ import annotations

import atexit
from typing import Optional, Mapping, Any

from flask import Flask
from flask_wtf import CSRFProtect

from .config import settings
from .constants import ALL_SIZES
from .products import bp as products_bp
from .history import bp as history_bp
from .sales import bp as sales_bp
from .shipping import bp as shipping_bp
from .allegro import bp as allegro_bp
from . import print_agent
from .app import bp as main_bp, start_print_agent, ensure_db_initialized
from .diagnostics import bp as diagnostics_bp
import os
from .db import configure_engine
from alembic.config import Config
from alembic import command

_shutdown_registered = False


def _register_shutdown_hook() -> None:
    global _shutdown_registered
    if _shutdown_registered:
        return
    atexit.register(print_agent.stop_agent_thread)
    _shutdown_registered = True


def create_app(config: Optional[Mapping[str, Any]] = None) -> Flask:
    """Create and configure a :class:`Flask` application instance."""

    app = Flask(__name__)
    app.secret_key = settings.SECRET_KEY

    if config:
        app.config.update(config)

    configure_engine(settings.DB_PATH)

    CSRFProtect(app)
    app.jinja_env.globals["ALL_SIZES"] = ALL_SIZES

    app.register_blueprint(main_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(shipping_bp)
    app.register_blueprint(allegro_bp)
    app.register_blueprint(diagnostics_bp)

    for rule in list(app.url_map.iter_rules()):
        if rule.endpoint.startswith("main."):
            simple_endpoint = rule.endpoint.split(".", 1)[1]
            app.view_functions[simple_endpoint] = app.view_functions[rule.endpoint]
            app.url_map._rules_by_endpoint.setdefault(simple_endpoint, []).append(
                rule
            )

    with app.app_context():
        ensure_db_initialized(app)
        alembic_ini_path = os.path.join(app.root_path, '..', 'alembic.ini')
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option('sqlalchemy.url', f"sqlite:///{settings.DB_PATH}")
        command.upgrade(alembic_cfg, "head")

    start_print_agent(app)

    _register_shutdown_hook()

    @app.after_request
    def apply_security_headers(response):
        """Attach security headers to every response."""

        csp = (
            "default-src 'self'; "
            "img-src 'self' https://retrievershop.pl data:; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
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
