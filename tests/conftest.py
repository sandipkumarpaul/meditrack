import os
import sys

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, basedir)

import pytest
from app import create_app, db as _db
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    # The rate limiter's storage is a process-wide singleton (app/__init__.py
    # creates one Limiter shared across every create_app() call), so without
    # this, running many tests against fresh test apps in one pytest session
    # could trip login/signup limits and fail for reasons unrelated to the test.
    RATELIMIT_ENABLED = False


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db
