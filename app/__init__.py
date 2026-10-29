"""
SmartStock – Application Factory
Creates and configures the Flask application.
"""
from datetime import timedelta
import math

from flask import Flask, g, jsonify
from flask_wtf.csrf import CSRFProtect
from werkzeug.exceptions import ServiceUnavailable
from .config import get_config
from .db import init_db, close_db
from .indexes import ensure_indexes


def create_app(config_name: str = "default") -> Flask:
    """
    Application factory.

    Args:
        config_name: 'default', 'testing', or 'production'

    Returns:
        Configured Flask application instance.
    """
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )

    #  Load configuration 
    cfg = get_config(config_name)
    app.config.from_object(cfg)
    if not 4 <= app.config["BCRYPT_LOG_ROUNDS"] <= 31:
        raise RuntimeError("BCRYPT_LOG_ROUNDS must be between 4 and 31.")
    if app.config["SESSION_LIFETIME_MINUTES"] < 1:
        raise RuntimeError("SESSION_LIFETIME_MINUTES must be positive.")
    if app.config["STORE_LOW_STOCK_DEFAULT"] < 0:
        raise RuntimeError("STORE_LOW_STOCK_DEFAULT cannot be negative.")
    if (
        not math.isfinite(app.config["STORE_TAX_PERCENT"])
        or app.config["STORE_TAX_PERCENT"] < 0
    ):
        raise RuntimeError(
            "STORE_TAX_PERCENT must be a finite, non-negative number."
        )
    app.permanent_session_lifetime = timedelta(
        minutes=app.config["SESSION_LIFETIME_MINUTES"]
    )
    if config_name == "production" and (
        not app.config["SECRET_KEY"]
        or len(app.config["SECRET_KEY"]) < 32
        or app.config["SECRET_KEY"] in {
            "dev-secret-please-change",
            "change-this-to-a-long-random-string",
        }
    ):
        raise RuntimeError("Set a unique SECRET_KEY before starting in production.")

    CSRFProtect(app)

    #  Database lifecycle 
    init_db(app)
    app.teardown_appcontext(close_db)
    app.register_error_handler(
        503,
        lambda error: (
            jsonify({"status": "unavailable", "error": error.description}),
            503,
        ),
    )

    #  Ensure MongoDB indexes exist 
    with app.app_context():
        try:
            ensure_indexes(app)
        except ServiceUnavailable as exc:  # pragma: no cover
            app.logger.warning("Index creation skipped: %s", exc)

    #  Register blueprints 
    _register_blueprints(app)

    #  Register template helpers 
    _register_template_helpers(app)

    return app


def _register_blueprints(app: Flask) -> None:
    from .routes.main import main_bp
    from .routes.products import products_bp
    from .routes.suppliers import suppliers_bp
    from .routes.purchases import purchases_bp
    from .routes.sales import sales_bp
    from .routes.inventory import inventory_bp
    from .routes.reviews import reviews_bp
    from .routes.analytics import analytics_bp
    from .routes.auth import auth_bp
    from .routes.settings import settings_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(products_bp,   url_prefix="/products")
    app.register_blueprint(suppliers_bp,  url_prefix="/suppliers")
    app.register_blueprint(purchases_bp,  url_prefix="/purchases")
    app.register_blueprint(sales_bp,      url_prefix="/sales")
    app.register_blueprint(inventory_bp,  url_prefix="/inventory")
    app.register_blueprint(reviews_bp,    url_prefix="/reviews")
    app.register_blueprint(analytics_bp,  url_prefix="/analytics")
    app.register_blueprint(auth_bp,       url_prefix="/auth")
    app.register_blueprint(settings_bp,   url_prefix="/settings")


def _register_template_helpers(app: Flask) -> None:
    """Expose helpers to all Jinja2 templates."""
    import datetime
    from .models.user import has_permission

    @app.template_filter("inr")
    def inr_filter(value):
        """Format a number as Indian-style currency string."""
        try:
            v = float(str(value))
            # Indian numbering: after first three digits, groups of two
            s = f"{v:,.2f}"
            return f"{app.config['STORE_CURRENCY_SYMBOL']}\u00a0{s}"
        except (TypeError, ValueError):
            return value

    @app.template_filter("datefmt")
    def datefmt_filter(value, fmt="%d %b %Y"):
        if isinstance(value, str):
            try:
                value = datetime.datetime.fromisoformat(value)
            except ValueError:
                return value
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.strftime(fmt)
        return value

    @app.context_processor
    def inject_globals():
        return {
            "store_name": app.config.get("STORE_NAME", "SmartStock"),
            "currency_symbol": app.config.get("STORE_CURRENCY_SYMBOL", "₹"),
            "can": lambda resource, action: bool(
                g.current_user
                and has_permission(g.current_user.get("role", ""), resource, action)
            ),
        }
