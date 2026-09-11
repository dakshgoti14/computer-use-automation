.PHONY: install lint format typecheck test test-unit test-integration demo discover replay replay-not-found replay-error handoff benchmark run-api clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	$(PYTHON) -m playwright install chromium

lint:
	$(VENV)/bin/ruff check app demo_app tests scripts

format:
	$(VENV)/bin/ruff check --fix app demo_app tests scripts

typecheck:
	$(VENV)/bin/mypy app demo_app

test:
	$(PYTHON) -m pytest tests/ -v

test-unit:
	$(PYTHON) -m pytest tests/unit -v

test-integration:
	$(PYTHON) -m pytest tests/integration -v

demo:
	$(PYTHON) scripts/run_demo.py

discover:
	$(PYTHON) scripts/discover_capability.py --goal "Look up member 12345 and read their current savings balance" --member-id 12345

replay:
	$(PYTHON) scripts/replay_capability.py --capability capabilities/member_savings_lookup.json --member-id 12345

replay-not-found:
	$(PYTHON) scripts/replay_capability.py --capability capabilities/member_savings_lookup.json --member-id 99999 --run-kind errors/member_not_found

replay-error:
	$(PYTHON) scripts/replay_capability.py --capability capabilities/member_savings_lookup.json --member-id 40404 --run-kind errors/unexpected_error

handoff:
	$(PYTHON) scripts/demo_escalation_handoff.py

benchmark:
	$(PYTHON) scripts/benchmark_replay.py --capability capabilities/member_savings_lookup.json --member-id 12345 --runs 10

run-api:
	$(VENV)/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache
