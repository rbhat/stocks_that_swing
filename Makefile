PY := .venv/bin/python

setup:
	uv pip install --python $(PY) -e ".[dev]"

test:
	$(PY) -m pytest -q

fetch-roster:
	$(PY) scripts/fetch_study_roster.py

forward-eod:
	$(PY) scripts/forward_eod.py

forward-fill:
	$(PY) scripts/forward_fill.py

forward-monitor:
	$(PY) scripts/forward_monitor.py

.PHONY: setup test fetch-roster forward-eod forward-fill forward-monitor
