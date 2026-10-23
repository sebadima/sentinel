.PHONY: all run prep delete reformat show_all_records lint lint-fix format typecheck security check freeze test

all: run

prep:
	test -d .venv || python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.txt

freeze:
	.venv/bin/python -m pip freeze > requirements.txt

run:
	.venv/bin/gunicorn -w 2 -b 0.0.0.0:5040 --log-level debug --access-logfile - --error-logfile - --capture-output app:app

delete:
	bash delete_pg_records.sh

show_all_records:
	bash show_pg_records.sh $(LIMIT)

# Analisi statica
lint:
	-.venv/bin/ruff check app.py || true

lint-fix:
	.venv/bin/ruff check --fix app.py

format:
	.venv/bin/ruff format app.py

reformat: lint-fix format

typecheck:
	-.venv/bin/mypy --follow-imports=skip --ignore-missing-imports app.py || true

security:
	-.venv/bin/bandit app.py || true

# Suite di test pytest in-memory
test:
	.venv/bin/python -m pytest -v -s tests/

# Controlli manuali locali
check: lint typecheck security test
