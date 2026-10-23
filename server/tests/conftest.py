
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

# Usa esclusivamente il database PostgreSQL dedicato ai test.
test_database_url = os.environ.get("TEST_DATABASE_URL", "").strip()

if not test_database_url:
    raise RuntimeError("TEST_DATABASE_URL non è configurata.")

parsed_url = urlparse(test_database_url)

if parsed_url.scheme != "postgresql+psycopg":
    raise RuntimeError(
        "TEST_DATABASE_URL deve usare postgresql+psycopg://."
    )

if parsed_url.path.lstrip("/") != "haccp_test":
    raise RuntimeError(
        "Test bloccati: TEST_DATABASE_URL deve puntare a haccp_test."
    )

# Imposta il database prima di importare app.py.
os.environ["DATABASE_URL"] = test_database_url
os.environ["SENTRY_DSN"] = ""

import sentry_sdk

sentry_sdk.init = lambda *args, **kwargs: None

import pytest
from app import app as flask_app, db


@pytest.fixture
def app():
    # Controlla il motore effettivamente creato da SQLAlchemy.
    engine_url = db.engine.url

    if engine_url.get_backend_name() != "postgresql":
        pytest.fail("Test bloccati: il database non è PostgreSQL.")

    if engine_url.database != "haccp_test":
        pytest.fail("Test bloccati: il database non è haccp_test.")

    flask_app.config["TESTING"] = True

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
