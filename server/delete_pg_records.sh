
#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f ".env" ]]; then
    echo "Errore: file .env non trovato."
    exit 1
fi

read -r -p "Confermi la cancellazione di TUTTI i record di haccp_log? [s/N] " conferma

if [[ "$conferma" != "s" && "$conferma" != "S" ]]; then
    echo "Operazione annullata."
    exit 0
fi

bin/python <<'PY'
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(".env")
url = os.environ.get("DATABASE_URL")

if not url:
    sys.exit("Errore: DATABASE_URL non configurata in .env")

engine = create_engine(url)

try:
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM haccp_log"))
        print(f"Record cancellati: {result.rowcount}")
finally:
    engine.dispose()
PY
