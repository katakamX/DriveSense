.PHONY: help install contracts-check simulator-check backend-check frontend-check check sim sim-headless up up-dev down logs

help:
	@echo "install          Install all Python packages and frontend dependencies"
	@echo "contracts-check  Ruff, mypy and pytest for the shared contracts"
	@echo "simulator-check  Ruff, mypy and pytest for the simulator"
	@echo "backend-check    Ruff, mypy and pytest"
	@echo "frontend-check   Typecheck, lint, format check and build"
	@echo "check            All of the above"
	@echo "sim              Launch the interactive simulator"
	@echo "sim-headless     Run the scripted demo drive and record JSONL"
	@echo "up              Start the production-oriented stack"
	@echo "up-dev          Start the development stack with hot reload"
	@echo "down            Stop the stack"
	@echo "logs            Tail service logs"

install:
	cd contracts && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
	cd simulator && python -m venv .venv \
		&& .venv/Scripts/python -m pip install -e ../contracts \
		&& .venv/Scripts/python -m pip install -e ".[dev]"
	cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
	cd frontend && npm install

contracts-check:
	cd contracts && .venv/Scripts/python -m ruff check . \
		&& .venv/Scripts/python -m ruff format --check . \
		&& .venv/Scripts/python -m mypy drivesense_contracts \
		&& .venv/Scripts/python -m pytest -q

simulator-check:
	cd simulator && .venv/Scripts/python -m ruff check . \
		&& .venv/Scripts/python -m ruff format --check . \
		&& .venv/Scripts/python -m mypy drivesense_sim \
		&& .venv/Scripts/python -m pytest -q

sim:
	cd simulator && .venv/Scripts/python -m drivesense_sim

sim-headless:
	cd simulator && .venv/Scripts/python -m drivesense_sim --headless --out ../data/recordings

backend-check:
	cd backend && .venv/Scripts/python -m ruff check . \
		&& .venv/Scripts/python -m ruff format --check . \
		&& .venv/Scripts/python -m mypy app \
		&& .venv/Scripts/python -m pytest -q

frontend-check:
	cd frontend && npm run typecheck && npm run lint && npm run format:check && npm run build

check: contracts-check simulator-check backend-check frontend-check

up:
	docker compose up --build

up-dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

down:
	docker compose down

logs:
	docker compose logs -f
