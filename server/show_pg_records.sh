#!/usr/bin/env bash
set -euo pipefail

LIMIT="${1:-3}"

if ! [[ "$LIMIT" =~ ^[1-9][0-9]*$ ]]; then
    echo "Errore: LIMIT deve essere un intero positivo."
    exit 1
fi

if [[ ! -f ".env" ]]; then
    echo "Errore: file .env non trovato."
    exit 1
fi

bin/python - "$LIMIT" <<'PY'
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

limit = int(sys.argv[1])
load_dotenv(".env")

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit("Errore: DATABASE_URL non configurata in .env")

engine = create_engine(url)

try:
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, timestamp, fw_version, status, drift, payload
                FROM haccp_log
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()

    if not rows:
        print("Nessun record trovato.")
    else:
        for row in rows:
            print("-" * 60)
            for key, value in row.items():
                print(f"{key}: {value}")
        print("-" * 60)
        print(f"Record visualizzati: {len(rows)}")
finally:
    engine.dispose()
PY
