
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Inserisce la root del progetto in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Carica le variabili d'ambiente prima di importare app.py
load_dotenv(PROJECT_ROOT / ".env")

# Impone il database dedicato ai test
test_db_url = os.environ.get("TEST_DATABASE_URL")

if not test_db_url:
    raise RuntimeError(
        "TEST_DATABASE_URL non configurata nel file .env"
    )

# Disabilita Sentry prima di importare app.py
os.environ["DATABASE_URL"] = test_db_url
os.environ["SENTRY_DSN"] = ""

import sentry_sdk

sentry_sdk.init = lambda *args, **kwargs: None

import pytest
from sqlalchemy.engine import make_url
from app import app as flask_app, db


@pytest.fixture
def app():
    flask_app.config["TESTING"] = True

    with flask_app.app_context():
        # Verifica il database effettivamente usato da SQLAlchemy
        database_name = db.engine.url.database

        if database_name != "haccp_test":
            raise RuntimeError(
                "TEST INTERROTTO: database non autorizzato: "
                f"{database_name!r}"
            )

        db.create_all()

        try:
            yield flask_app
        finally:
            db.session.remove()
            db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_check_update(client):
    response = client.get("/update/check")
    assert response.status_code == 200

    data = response.get_json()
    assert "version" in data
    assert "url" in data


def test_download_update_invalid_extension(client):
    response = client.get("/update/download/firmware.exe")
    assert response.status_code == 400


def test_ingest_co2_valid(client):
    payload = {
        "co2": 450.5,
        "temp": 22.1,
        "hum": 55.0,
        "mq3_raw": 120,
        "msg_id": 1,
    }

    response = client.post("/ingest/co2", json=payload)

    assert response.status_code == 200
    assert response.get_json()["status"] == "OK"


def test_ingest_co2_missing_co2(client):
    payload = {"temp": 22.1}

    response = client.post("/ingest/co2", json=payload)

    assert response.status_code == 400


def test_get_latest_co2(client):
    response = client.get("/api/co2/latest")
    assert response.status_code == 200


def test_ingest_esp32_missing_signature(client):
    payload = {"version": 955}

    response = client.post("/ingest", json=payload)

    assert response.status_code == 403


def test_ingest_esp32_valid(client):
    payload = {
        "voltage_0": 3.3,
        "version": 955,
        "status": 0,
        "drift": 0,
        "dht_temp": 24.5,
    }

    response = client.post("/ingest", json=payload)

    assert response.status_code == 201
    assert response.get_json()["status"] == "OK"


def test_get_data(client):
    response = client.get("/data")

    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


def test_export_csv(client):
    response = client.get("/export/24h")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
