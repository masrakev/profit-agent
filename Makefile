.PHONY: up down migrate test lint format eval

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
	@echo "Evaluation suite not implemented yet (planned for Task 2)."
