"""
SmartStock – Configuration
Reads settings from environment variables (via .env in development).
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()  # reads .env when present; silently ignored in production


class BaseConfig:
    # Flask core
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-please-change")
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    WTF_CSRF_ENABLED: bool = True

    # MongoDB
    MONGO_URI: str = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
    MONGO_DB_NAME: str = os.environ.get("MONGO_DB_NAME", "smartstock")

    # Store settings
    STORE_NAME: str = os.environ.get("STORE_NAME", "SmartStock Electronics")
    STORE_CURRENCY: str = os.environ.get("STORE_CURRENCY", "INR")
    STORE_CURRENCY_SYMBOL: str = os.environ.get("STORE_CURRENCY_SYMBOL", "₹")
    STORE_TAX_PERCENT: float = float(os.environ.get("STORE_TAX_PERCENT", "18"))
    STORE_INVOICE_PREFIX: str = os.environ.get("STORE_INVOICE_PREFIX", "INV")
    STORE_LOW_STOCK_DEFAULT: int = int(os.environ.get("STORE_LOW_STOCK_DEFAULT", "5"))

    # Security
    SESSION_LIFETIME_MINUTES: int = int(
        os.environ.get("SESSION_LIFETIME_MINUTES", "120")
    )
    BCRYPT_LOG_ROUNDS: int = int(os.environ.get("BCRYPT_LOG_ROUNDS", "12"))

    # Flask host / port (used by run.py)
    FLASK_HOST: str = os.environ.get("FLASK_HOST", "127.0.0.1")
    FLASK_PORT: int = int(os.environ.get("FLASK_PORT", "5000"))


class DevelopmentConfig(BaseConfig):
    DEBUG: bool = True
    SESSION_COOKIE_SECURE: bool = False
    WTF_CSRF_ENABLED: bool = True


class TestingConfig(BaseConfig):
    TESTING: bool = True
    DEBUG: bool = True
    MONGO_DB_NAME: str = "smartstock_test"
    WTF_CSRF_ENABLED: bool = False
    SESSION_COOKIE_SECURE: bool = False
    SECRET_KEY: str = "test-secret"


class ProductionConfig(BaseConfig):
    DEBUG: bool = False
    SESSION_COOKIE_SECURE: bool = True  # requires HTTPS
    SESSION_COOKIE_SAMESITE: str = "Strict"
    SECRET_KEY: str | None = os.environ.get("SECRET_KEY")


_CONFIG_MAP = {
    "default": DevelopmentConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str = "default"):
    try:
        return _CONFIG_MAP[name]
    except KeyError as exc:
        raise ValueError(f"Unknown application configuration: {name}") from exc
