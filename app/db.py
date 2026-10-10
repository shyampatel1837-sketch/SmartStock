"""
SmartStock – Database Layer
-----------------------------
Centralises PyMongo client lifecycle.
One MongoClient per process; one connection-pool shared across requests.
"""
from __future__ import annotations

import logging
from typing import Optional

from flask import Flask, current_app, g
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ConfigurationError

logger = logging.getLogger(__name__)

# Module-level client (created once per process)
_client: Optional[MongoClient] = None


def init_db(app: Flask) -> None:
    """
    Create the MongoClient and store it on the app object.
    Called once from the application factory.
    """
    global _client
    uri = app.config["MONGO_URI"]
    try:
        _client = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
        )
        # Verify connectivity at startup
        _client.admin.command("ping")
        logger.info("MongoDB connected: %s", uri)
    except (ConnectionFailure, ConfigurationError) as exc:
        logger.error("MongoDB connection failed: %s", exc)
        # Store the error so the app can surface it clearly
        app.config["MONGO_CONNECT_ERROR"] = str(exc)
        _client = None

    app.extensions["mongo_client"] = _client


def get_db() -> Database:
    """
    Return the database for the current request context.
    Caches the reference in Flask's `g` object.
    """
    if "db" not in g:
        client = current_app.extensions.get("mongo_client")
        if client is None:
            raise RuntimeError(
                "MongoDB client is not initialised. "
                "Check MONGO_URI in your .env file."
            )
        g.db = client[current_app.config["MONGO_DB_NAME"]]
    return g.db


def close_db(exc=None) -> None:
    """Teardown: remove the db reference from g (client stays open)."""
    g.pop("db", None)


def get_client() -> Optional[MongoClient]:
    """Return the module-level MongoClient (used by indexes script)."""
    return _client


def ping() -> bool:
    """Return True if MongoDB is reachable."""
    try:
        client = current_app.extensions.get("mongo_client")
        if client is None:
            return False
        client.admin.command("ping")
        return True
    except Exception:
        return False
