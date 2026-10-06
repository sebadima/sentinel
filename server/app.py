import csv
import io
import os
import sqlite3
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from werkzeug.utils import secure_filename
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
    abort,
)

app = Flask(__name__)

DB_FILE = "haccp_monitor.db"
TZ_ITALY = ZoneInfo("Europe/Rome")
LATEST_FW_VERSION = 876
FIRMWARE_DIR = os.path.join(app.root_path, "firmware_builds")
os.makedirs(FIRMWARE_DIR, exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS haccp_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                fw_version INTEGER NOT NULL,
                status INTEGER DEFAULT 0,
                drift INTEGER DEFAULT 0,
                payload TEXT NOT NULL
            )
        """)


init_db()


def query_db(query, args=(), one=False):
    with get_db_connection() as conn:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        return (rv[0] if rv else None) if one else rv


@app.route("/update/check", methods=["GET"])
def check_update():
    return jsonify(
        {
            "version": LATEST_FW_VERSION,
            "url": f"http://{request.host}/update/download/sentinel_v{LATEST_FW_VERSION}.bin",
        }
    )


@app.route("/update/download/<filename>", methods=["GET"])
def download_update(filename):
    sec_name = secure_filename(filename)
    if not sec_name.endswith(".bin"):
        abort(400)

    print(f"[OTA] Serving binary: {sec_name} to {request.remote_addr}")
    return send_from_directory(FIRMWARE_DIR, sec_name, as_attachment=True)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"), "favicon.svg", mimetype="image/svg+xml"
    )


@app.route("/ingest", methods=["POST"])
def ingest():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        print(f"[ERR_JSON] Payload malformato da {request.remote_addr}: {e}")
        return jsonify({"status": "ERROR", "msg": "Invalid JSON data"}), 400

    print(f"\n{'=' * 60}")
    print(
        f"[RAW INGEST] RICEZIONE DA {request.remote_addr} AL TEMPO SERVER {datetime.now(TZ_ITALY)}"
    )
    print("=" * 60)
    print(json.dumps(data, indent=4))
    print(f"{'=' * 60}\n")

    ts_hw = data.get("timestamp")

    if not ts_hw or str(ts_hw).strip() == "":
        ts_hw = datetime.now(TZ_ITALY).strftime("%Y-%m-%d %H:%M:%S")

    fw_version = data.get("version", 0)
    status = data.get("status", 0)
    drift = data.get("drift", 0)

    meta_keys = {"timestamp", "version", "status", "drift"}
    payload_dinamico = {k: v for k, v in data.items() if k not in meta_keys}

    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO haccp_log (timestamp, fw_version, status, drift, payload) VALUES (?, ?, ?, ?, ?)",
                (ts_hw, fw_version, status, drift, json.dumps(payload_dinamico)),
            )
        print(f"[{ts_hw}] INGEST_OK | V:{fw_version} | STATUS:{status}")
        return jsonify({"status": "OK"}), 201

    except sqlite3.Error as db_err:
        print(f"[ERR_DB_WRITE] {db_err}")
        return jsonify({"status": "ERROR", "msg": "Internal storage failure"}), 500


@app.route("/data")
def get_data():
    query = """
        SELECT
            id, timestamp, fw_version, status, drift,
            CAST(json_extract(payload, '$.voltage_0') AS REAL) AS voltage_0,
            CAST(json_extract(payload, '$.voltage_1') AS REAL) AS voltage_1,
            CAST(json_extract(payload, '$.voltage_2') AS REAL) AS voltage_2,
            CAST(json_extract(payload, '$.voltage_3') AS REAL) AS voltage_3,
            CAST(json_extract(payload, '$.ads_ch0') AS REAL) AS ads_ch0,
            CAST(json_extract(payload, '$.ads_ch1') AS REAL) AS ads_ch1,
            CAST(json_extract(payload, '$.ads_ch2') AS REAL) AS ads_ch2,
            CAST(json_extract(payload, '$.ads_ch3') AS REAL) AS ads_ch3,
            CAST(json_extract(payload, '$.dht_temp') AS REAL) AS dht_temp,
            CAST(json_extract(payload, '$.dht_hum') AS REAL) AS dht_hum,
            CAST(json_extract(payload, '$.rtc_temp') AS REAL) AS rtc_temp
        FROM haccp_log
        ORDER BY timestamp DESC
        LIMIT 100
    """
    data = query_db(query)
    return jsonify([dict(row) for row in data])


@app.route("/export/<period>")
def export_csv(period):
    days = {"24h": 1, "week": 7, "month": 30}.get(period, 1)
    since = (datetime.now(TZ_ITALY) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    query = """
        SELECT id, timestamp, fw_version, status, drift,
        json_extract(payload, '$.voltage_0') AS voltage_0,
        json_extract(payload, '$.voltage_1') AS voltage_1,
        json_extract(payload, '$.voltage_2') AS voltage_2,
        json_extract(payload, '$.voltage_3') AS voltage_3,
        json_extract(payload, '$.ads_ch0') AS ads_ch0,
        json_extract(payload, '$.ads_ch1') AS ads_ch1,
        json_extract(payload, '$.ads_ch2') AS ads_ch2,
        json_extract(payload, '$.ads_ch3') AS ads_ch3,
        json_extract(payload, '$.dht_temp') AS dht_temp,
        json_extract(payload, '$.dht_hum') AS dht_hum,
        json_extract(payload, '$.rtc_temp') AS rtc_temp
        FROM haccp_log
        WHERE timestamp > ?
        ORDER BY timestamp ASC
    """
    rows = query_db(query, (since,))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "TIMESTAMP",
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
            "FW_VER",
        ]
    )

    for r in rows:
        writer.writerow(
            [
                r["id"],
                r["timestamp"],
                r["voltage_0"],
                r["voltage_1"],
                r["voltage_2"],
                r["voltage_3"],
                r["ads_ch0"],
                r["ads_ch1"],
                r["ads_ch2"],
                r["ads_ch3"],
                r["dht_temp"],
                r["dht_hum"],
                r["status"],
                r["drift"],
                r["rtc_temp"],
                r["fw_version"],
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=SENTINEL_DUMP_{period.upper()}.csv"
        },
    )


@app.route("/")
def index():
    query = """
        SELECT id, timestamp, fw_version, status, drift,
            CAST(json_extract(payload, '$.voltage_0') AS REAL) AS voltage_0,
            CAST(json_extract(payload, '$.voltage_1') AS REAL) AS voltage_1,
            CAST(json_extract(payload, '$.voltage_2') AS REAL) AS voltage_2,
            CAST(json_extract(payload, '$.voltage_3') AS REAL) AS voltage_3,
            CAST(json_extract(payload, '$.ads_ch0') AS REAL) AS ads_ch0,
            CAST(json_extract(payload, '$.ads_ch1') AS REAL) AS ads_ch1,
            CAST(json_extract(payload, '$.ads_ch2') AS REAL) AS ads_ch2,
            CAST(json_extract(payload, '$.ads_ch3') AS REAL) AS ads_ch3,
            CAST(json_extract(payload, '$.dht_temp') AS REAL) AS dht_temp,
            CAST(json_extract(payload, '$.dht_hum') AS REAL) AS dht_hum,
            CAST(json_extract(payload, '$.rtc_temp') AS REAL) AS rtc_temp
        FROM haccp_log
        ORDER BY timestamp DESC
        LIMIT 100
    """
    data = query_db(query)
    return render_template("dashboard.html", data=[dict(row) for row in data])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5040, debug=True, threaded=True)
