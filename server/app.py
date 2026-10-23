#!/usr/bin/env python3

import csv
import io
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import sentry_sdk
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI
from werkzeug.utils import secure_filename

# ============================================================
# CONFIG & SENTRY INTEGRATION
# ============================================================

load_dotenv()

SENTRY_DSN = os.environ.get("SENTRY_DSN")

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0,
    )


app = Flask(__name__)

TZ_ITALY = ZoneInfo("Europe/Rome")

LATEST_FW_VERSION = 958


# ============================================================
# DATABASE POSTGRESQL & ALCHEMY
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/haccp"
)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_size": 10,
    "pool_recycle": 3600,
}

db = SQLAlchemy(app)
migrate = Migrate(app, db)


class HaccpLog(db.Model): # type: ignore
    __tablename__ = "haccp_log"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(db.String, nullable=False)
    fw_version = db.Column(db.Integer, nullable=False)
    status = db.Column(db.Integer, default=0)
    drift = db.Column(db.Integer, default=0)
    payload = db.Column(db.Text, nullable=False)


def _parse_payload(row: HaccpLog) -> dict:

    try:
        p = json.loads(row.payload)
    except Exception:
        p = {}

    return {
        "id": row.id,
        "timestamp": row.timestamp,
        "fw_version": row.fw_version,
        "status": row.status,
        "drift": row.drift,
        "tilt_density": p.get("tilt_density"),
        "abv_est": p.get("abv_est"),
        "voltage_0": p.get("voltage_0"),
        "voltage_1": p.get("voltage_1"),
        "voltage_2": p.get("voltage_2"),
        "voltage_3": p.get("voltage_3"),
        "ads_ch0": p.get("ads_ch0"),
        "ads_ch1": p.get("ads_ch1"),
        "ads_ch2": p.get("ads_ch2"),
        "ads_ch3": p.get("ads_ch3"),
        "dht_temp": p.get("dht_temp"),
        "dht_hum": p.get("dht_hum"),
        "rtc_temp": p.get("rtc_temp"),
        "co2": p.get("co2"),
        "node_co2_temp": p.get("temp"),
        "node_co2_hum": p.get("hum"),
        "co2_msg_id": p.get("co2_msg_id"),
    }


# ============================================================
# AI
# ============================================================

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.scaleway.ai/v1")

MODEL_NAME = os.environ.get("MODEL", "llama-3.1-70b-instruct")

ai_client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_API_BASE,
)

# ============================================================
# FIRMWARE
# ============================================================

FIRMWARE_DIR = os.path.join(
    app.root_path,
    "firmware_builds",
)

os.makedirs(
    FIRMWARE_DIR,
    exist_ok=True,
)


# ============================================================
# CACHE CO2
# ============================================================

LAST_BT_CO2_DATA = {
    "co2": 0.0,
    "temp": 0.0,
    "hum": 0.0,
    "mq3_raw": 0,
    "msg_id": 0,
    "updated_at": None,
    "source": "BLE_RPI4",
}


# ============================================================
# CACHE FERMENTAZIONE
# ============================================================

LAST_SIMULATION_DATA = {
    "tilt_density": None,
    "abv_est": None,
    "updated_at": None,
}


# ============================================================
# LOG
# ============================================================


def log(msg: str) -> None:
    ts = datetime.now(TZ_ITALY).strftime("%H:%M:%S")

    print(
        f"[{ts}] {msg}",
        flush=True,
    )


# ============================================================
# OTA
# ============================================================


# ------------------------------------------------------------
# ROTTA TEST SENTRY (Forza un'eccezione 500)
# ------------------------------------------------------------
@app.route("/errore_forzato", methods=["GET"])
def errore_forzato():
    try:
        raise RuntimeError("Test eccezione forzata per Sentry")
    except Exception as e:
        sentry_sdk.capture_exception(e)
        sentry_sdk.flush(timeout=2.0)  # Blocca 2 secondi max per spedire via rete
        raise e


@app.route(
    "/update/check",
    methods=["GET"],
)
def check_update():

    return jsonify(
        {
            "version": LATEST_FW_VERSION,
            "url": (
                f"http://{request.host}"
                f"/update/download/"
                f"sentinel_v{LATEST_FW_VERSION}.bin"
            ),
        }
    )


@app.route(
    "/update/download/<filename>",
    methods=["GET"],
)
def download_update(filename):

    sec_name = secure_filename(filename)

    if not sec_name.endswith(".bin"):
        abort(400)

    return send_from_directory(
        FIRMWARE_DIR,
        sec_name,
        as_attachment=True,
    )


# ============================================================
# FAVICON
# ============================================================


@app.route("/favicon.ico")
def favicon():

    return send_from_directory(
        os.path.join(
            app.root_path,
            "static",
        ),
        "favicon.svg",
        mimetype="image/svg+xml",
    )


# ============================================================
# BLE -> FLASK
# ============================================================


@app.route(
    "/ingest/co2",
    methods=["POST"],
)
def ingest_co2():

    global LAST_BT_CO2_DATA

    log("[BLE][HTTP] POST /ingest/co2 ricevuto")

    try:
        data = request.get_json(force=True)

    except Exception as e:
        log(f"[BLE][JSON_ERR] {e}")

        return jsonify(
            {
                "status": "ERROR",
                "msg": "Invalid JSON",
            }
        ), 400

    log(f"[BLE][RAW] {data}")

    if not isinstance(data, dict):
        log("[BLE][REJECTED] JSON object required")

        return jsonify(
            {
                "status": "ERROR",
                "msg": "JSON object required",
            }
        ), 400

    if "co2" not in data:
        log("[BLE][REJECTED] missing co2")

        return jsonify(
            {
                "status": "ERROR",
                "msg": "Missing co2",
            }
        ), 400

    try:
        co2 = float(
            data.get(
                "co2",
                0,
            )
        )

        temp = float(
            data.get(
                "temp",
                0.0,
            )
        )

        hum = float(
            data.get(
                "hum",
                0.0,
            )
        )

        mq3_raw = int(
            data.get(
                "mq3_raw",
                0,
            )
        )

        msg_id = int(
            data.get(
                "msg_id",
                0,
            )
        )

    except (
        TypeError,
        ValueError,
    ) as e:
        log(f"[BLE][VALUE_ERR] {e}")

        return jsonify(
            {
                "status": "ERROR",
                "msg": "Invalid sensor values",
            }
        ), 400

    now_str = datetime.now(TZ_ITALY).strftime("%Y-%m-%d %H:%M:%S")

    LAST_BT_CO2_DATA = {
        "co2": co2,
        "temp": temp,
        "hum": hum,
        "mq3_raw": mq3_raw,
        "msg_id": msg_id,
        "updated_at": now_str,
        "source": "BLE_RPI4",
    }

    log(f"[BLE][CACHE UPDATED] MSG_ID={msg_id} CO2={co2} TEMP={temp} HUM={hum}")

    return jsonify(
        {
            "status": "OK",
            "msg": "CO2 data received",
            "msg_id": msg_id,
        }
    ), 200


# ============================================================
# DEBUG CO2
# ============================================================


@app.route(
    "/api/co2/latest",
    methods=["GET"],
)
def get_latest_co2():

    log(
        "[BLE][API] /api/co2/latest "
        f"CO2={LAST_BT_CO2_DATA['co2']} "
        f"MSG_ID={LAST_BT_CO2_DATA['msg_id']} "
        f"UPDATED={LAST_BT_CO2_DATA['updated_at']}"
    )

    return jsonify(LAST_BT_CO2_DATA), 200


# ============================================================
# DEBUG BLE
# ============================================================


@app.route(
    "/api/co2/debug",
    methods=["GET"],
)
def debug_co2():

    return jsonify(
        {
            "status": "OK",
            "cache": LAST_BT_CO2_DATA,
            "server_time": datetime.now(TZ_ITALY).strftime("%Y-%m-%d %H:%M:%S"),
        }
    ), 200


# ============================================================
# FERMENTAZIONE
# ============================================================


@app.route(
    "/ingest/fermentation",
    methods=["POST"],
)
def ingest_fermentation():

    global LAST_SIMULATION_DATA

    try:
        data = request.get_json(force=True)

        LAST_SIMULATION_DATA["tilt_density"] = data.get("tilt_density")

        LAST_SIMULATION_DATA["abv_est"] = data.get("abv_est")

        LAST_SIMULATION_DATA["updated_at"] = datetime.now(TZ_ITALY).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        log(
            "[INGEST] FERMENTATION "
            f"density="
            f"{LAST_SIMULATION_DATA['tilt_density']} "
            f"abv="
            f"{LAST_SIMULATION_DATA['abv_est']}"
        )

        return jsonify(
            {
                "status": "OK",
                "msg": "In-memory cache updated",
            }
        ), 200

    except Exception as e:
        log(f"[INGEST] FERMENTATION_ERR {e}")

        return jsonify(
            {
                "status": "ERROR",
                "msg": "Invalid payload",
            }
        ), 400


# ============================================================
# INGEST ESP32
# ============================================================


@app.route(
    "/ingest",
    methods=["POST"],
)
def ingest():

    try:
        data = request.get_json(force=True)

    except Exception as e:
        log(f"[INGEST] JSON_ERR {e}")

        return jsonify(
            {
                "status": "ERROR",
                "msg": "Invalid JSON data",
            }
        ), 400

    if "voltage_0" not in data:
        log("[INGEST] REJECTED missing voltage_0")

        return jsonify(
            {
                "status": "ERROR",
                "msg": ("Hardware signature check fallito."),
            }
        ), 403

    ts_hw = data.get("timestamp")

    if not ts_hw or str(ts_hw).strip() == "":
        ts_hw = datetime.now(TZ_ITALY).isoformat(timespec="seconds")

    fw_version = data.get(
        "version",
        0,
    )

    status = data.get(
        "status",
        0,
    )

    drift = data.get(
        "drift",
        0,
    )

    meta_keys = {
        "timestamp",
        "version",
        "status",
        "drift",
    }

    payload_dinamico = {
        key: value for key, value in data.items() if key not in meta_keys
    }

    # --------------------------------------------------------
    # CO2 BLE
    # --------------------------------------------------------

    if LAST_BT_CO2_DATA["updated_at"] is not None:
        payload_dinamico["co2"] = LAST_BT_CO2_DATA["co2"]

        payload_dinamico["temp"] = LAST_BT_CO2_DATA["temp"]

        payload_dinamico["hum"] = LAST_BT_CO2_DATA["hum"]

        payload_dinamico["co2_msg_id"] = LAST_BT_CO2_DATA["msg_id"]

        payload_dinamico["co2_updated_at"] = LAST_BT_CO2_DATA["updated_at"]

        log(
            "[INGEST] CO2 BLE associato "
            f"MSG_ID={LAST_BT_CO2_DATA['msg_id']} "
            f"CO2={LAST_BT_CO2_DATA['co2']}"
        )

    else:
        log("[INGEST] Nessun dato CO2 BLE presente in cache")

    # --------------------------------------------------------
    # FERMENTAZIONE
    # --------------------------------------------------------

    if LAST_SIMULATION_DATA["updated_at"] is not None:
        if LAST_SIMULATION_DATA["tilt_density"] is not None:
            payload_dinamico["tilt_density"] = LAST_SIMULATION_DATA["tilt_density"]

        if LAST_SIMULATION_DATA["abv_est"] is not None:
            payload_dinamico["abv_est"] = LAST_SIMULATION_DATA["abv_est"]

    # --------------------------------------------------------
    # DATABASE ALCHEMY
    # --------------------------------------------------------

    try:
        new_log = HaccpLog(
            timestamp=ts_hw,
            fw_version=fw_version,
            status=status,
            drift=drift,
            payload=json.dumps(payload_dinamico),
        )

        db.session.add(new_log)

        db.session.commit()

        log(
            "[INGEST] OK "
            f"V={fw_version} "
            f"STATUS={status} "
            f"CO2="
            f"{payload_dinamico.get('co2', '-')}"
        )

        return jsonify({"status": "OK"}), 201

    except Exception as db_err:
        db.session.rollback()

        log(f"[INGEST] DB_ERR {db_err}")

        return jsonify(
            {
                "status": "ERROR",
                "msg": "Internal storage failure",
            }
        ), 500


# ============================================================
# ANALISI FERMENTAZIONE
# ============================================================


@app.route(
    "/api/analyze",
    methods=["GET"],
)
def analyze_fermentation():

    rows = HaccpLog.query.order_by(HaccpLog.id.desc()).limit(30).all()

    if not rows:
        return jsonify(
            {
                "status": "EMPTY",
                "msg": "Nessun dato disponibile",
            }
        ), 200

    history = [_parse_payload(row) for row in rows]

    system_prompt = (
        "Sei un assistente tecnico esperto "
        "di analisi di processi fermentativi "
        "industriali e monitoraggio IoT. "
        "Analizza la serie temporale fornita "
        "in formato JSON. Valuta: "
        "1) Stato e fase attuale della "
        "fermentazione in base a densità "
        "(tilt_density) ed estrazione "
        "alcolica (abv_est). "
        "2) Stabilita termica ed eventuale "
        "presenza di anomalia nei valori "
        "di CO2 o sonda PT1000/RTC. "
        "3) Valutazione della dinamica "
        "(stasi vs conversione attiva). "
        "Fornisci una risposta sintetica, "
        "diretta, tecnica e senza convenevoli."
    )

    try:
        response = ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        history,
                        indent=2,
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=500,
        )

        analysis_text = response.choices[0].message.content.strip()

        log("[ANALYZE] OK")

        return jsonify(
            {
                "status": "OK",
                "analysis": analysis_text,
            }
        ), 200

    except Exception as e:
        log(f"[ANALYZE] ERR {e}")

        return jsonify(
            {
                "status": "ERROR",
                "msg": (f"Errore inferenza LLM: {str(e)}"),
            }
        ), 500


# ============================================================
# DATA
# ============================================================


@app.route("/data")
def get_data():

    rows = HaccpLog.query.order_by(HaccpLog.timestamp.desc()).limit(100).all()

    return jsonify([_parse_payload(row) for row in rows])


# ============================================================
# EXPORT CSV
# ============================================================


@app.route("/export/<period>")
def export_csv(period):

    days = {
        "24h": 1,
        "week": 7,
        "month": 30,
    }.get(
        period,
        1,
    )

    since = (datetime.now(TZ_ITALY) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    rows = (
        HaccpLog.query.filter(HaccpLog.timestamp > since)
        .order_by(HaccpLog.timestamp.asc())
        .all()
    )

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow(
        [
            "ID",
            "TIMESTAMP",
            "TILT_DENSITY",
            "ABV_EST",
            "VOLTAGE_0",
            "VOLTAGE_1",
            "VOLTAGE_2",
            "VOLTAGE_3",
            "ADS_CH0",
            "ADS_CH1",
            "ADS_CH2",
            "ADS_CH3",
            "DHT_TEMP",
            "DHT_HUM",
            "STATUS",
            "DRIFT",
            "RTC_TEMP_CORE",
            "CO2_PPM",
            "CO2_TEMP",
            "CO2_HUM",
            "CO2_MSG_ID",
            "FW_VER",
        ]
    )

    for row_obj in rows:
        row = _parse_payload(row_obj)

        writer.writerow(
            [
                row["id"],
                row["timestamp"],
                row["tilt_density"],
                row["abv_est"],
                row["voltage_0"],
                row["voltage_1"],
                row["voltage_2"],
                row["voltage_3"],
                row["ads_ch0"],
                row["ads_ch1"],
                row["ads_ch2"],
                row["ads_ch3"],
                row["dht_temp"],
                row["dht_hum"],
                row["status"],
                row["drift"],
                row["rtc_temp"],
                row["co2"],
                row["node_co2_temp"],
                row["node_co2_hum"],
                row["co2_msg_id"],
                row["fw_version"],
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=SENTINEL_DUMP_{period.upper()}.csv"
            )
        },
    )


# ============================================================
# DASHBOARD
# ============================================================


@app.route("/")
def index():

    rows = HaccpLog.query.order_by(HaccpLog.timestamp.desc()).limit(100).all()

    return render_template(
        "dashboard.html",
        data=[_parse_payload(row) for row in rows],
    )


# ============================================================
# MAIN
# ============================================================

