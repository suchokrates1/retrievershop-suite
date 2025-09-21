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

    CSRFProtect(app)
    app.jinja_env.globals["ALL_SIZES"] = ALL_SIZES

    app.register_blueprint(main_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(shipping_bp)
    app.register_blueprint(allegro_bp)

    for rule in list(app.url_map.iter_rules()):
        if rule.endpoint.startswith("main."):
            simple_endpoint = rule.endpoint.split(".", 1)[1]
            app.view_functions[simple_endpoint] = app.view_functions[rule.endpoint]
            app.url_map._rules_by_endpoint.setdefault(simple_endpoint, []).append(
                rule
            )

    app.before_first_request(lambda: ensure_db_initialized(app))
    app.before_first_request(lambda: start_print_agent(app))

    _register_shutdown_hook()

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Initialize the application database."""
        with app.app_context():
            ensure_db_initialized(app)

    return app
