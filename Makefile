PY := .venv/bin/python

setup:
	uv pip install --python $(PY) -e ".[dev]"

test:
	$(PY) -m pytest -q

fetch-roster:
	$(PY) scripts/fetch_study_roster.py

.PHONY: setup test fetch-roster
