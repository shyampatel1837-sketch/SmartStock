from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from app.config import ProductionConfig
from app.routes import auth as auth_routes


def test_offline_health_returns_service_unavailable(client):
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json == {"status": "unavailable", "db": False}


def test_login_is_available_without_database(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b'name="username"' in response.data


def test_database_backed_session_request_fails_clearly(client):
    with client.session_transaction() as session:
        session["user_id"] = "0123456789abcdef01234567"
    response = client.get("/dashboard")
    assert response.status_code == 503
    assert b"MongoDB database is unavailable" in response.data


def test_csrf_protects_login_post(client):
    response = client.post("/auth/login", data={"username": "user", "password": "pass"})
    assert response.status_code == 400
    assert b"CSRF" in response.data


def test_csrf_protects_logout_post(client):
    response = client.post("/auth/logout")
    assert response.status_code == 400
    assert b"CSRF" in response.data


def test_inventory_role_cannot_read_sales_or_customer_details(
    client, monkeypatch
):
    monkeypatch.setattr(auth_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        auth_routes,
        "get_current_user",
        lambda _db: {
            "_id": "0123456789abcdef01234567",
            "role": "inventory",
        },
    )
    with client.session_transaction() as session:
        session["user_id"] = "0123456789abcdef01234567"

    response = client.get("/sales/")

    assert response.status_code == 403


def test_all_templates_parse(application):
    template_root = Path(application.root_path).parent / "templates"
    template_names = [
        path.relative_to(template_root).as_posix()
        for path in template_root.rglob("*.html")
    ]
    assert template_names
    for template_name in template_names:
        application.jinja_env.get_template(template_name)


def test_production_requires_a_real_secret_key(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "change-this-to-a-long-random-string")
    with pytest.raises(RuntimeError, match="unique SECRET_KEY"):
        create_app("production")
