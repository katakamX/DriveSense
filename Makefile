.PHONY: help install backend-check frontend-check check up up-dev down logs

help:
	@echo "install         Install backend and frontend dependencies"
	@echo "backend-check   Ruff, mypy and pytest"
	@echo "frontend-check  Typecheck, lint, format check and build"
	@echo "check           Both of the above"
	@echo "up              Start the production-oriented stack"
	@echo "up-dev          Start the development stack with hot reload"
	@echo "down            Stop the stack"
	@echo "logs            Tail service logs"

install:
	cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
	cd frontend && npm install

backend-check:
	cd backend && .venv/Scripts/python -m ruff check . \
		&& .venv/Scripts/python -m ruff format --check . \
		&& .venv/Scripts/python -m mypy app \
		&& .venv/Scripts/python -m pytest -q

frontend-check:
	cd frontend && npm run typecheck && npm run lint && npm run format:check && npm run build

check: backend-check frontend-check

up:
	docker compose up --build

up-dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

down:
	docker compose down

logs:
	docker compose logs -f
