import pytest

import app as app_package


@pytest.fixture
def application(monkeypatch):
    def offline_init(application):
        application.extensions["mongo_client"] = None

    monkeypatch.setattr(app_package, "init_db", offline_init)
    monkeypatch.setattr(app_package, "ensure_indexes", lambda application: None)
    application = app_package.create_app("testing")
    application.config["WTF_CSRF_ENABLED"] = True
    return application


@pytest.fixture
def client(application):
    return application.test_client()
