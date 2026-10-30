.PHONY: up down migrate test lint format eval eval-dev scenarios smoke-live api worker scheduler demo

up:
	docker compose up -d --wait
	uv run alembic upgrade head

down:
	docker compose down

migrate:
	uv run alembic upgrade head

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format:
	uv run ruff check --fix .
	uv run ruff format .

eval:
	uv run python -m bench.runner

eval-dev:
	uv run python -m bench.runner --suite dev

scenarios:
	uv run python -m bench.scenarios.build

smoke-live:
	uv run python scripts/smoke_live.py

api:
	uv run uvicorn app.api.main:app --app-dir backend

worker:
	uv run python -m app.executor --loop 30

scheduler:
	uv run arq app.scheduler.worker.WorkerSettings

demo:
	uv run python -m bench.demo
