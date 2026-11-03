.PHONY: up down migrate test lint format web web-install web-lint web-test web-audit eval eval-dev scenarios smoke-live smoke-whatsapp api demo-api e2e openapi worker scheduler demo-seed demo demo-whatsapp

up:
	docker compose up -d --wait
	uv run alembic upgrade head

down:
	docker compose down

migrate:
	uv run alembic upgrade head

test:
	uv run pytest
	$(MAKE) web-test

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	$(MAKE) web-lint

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

smoke-whatsapp:
	uv run python scripts/whatsapp_smoke.py

api:
	uv run uvicorn app.api.main:app --app-dir backend

# The API on the demo store: its recorded model exchanges, replayed at their recorded pace.
demo-api:
	uv run python -m bench.demo_serve api

# The demo script end to end in a real browser, on a fresh demo seed (needs `make up`, and
# ports 8000 and 3000 free: it starts its own API, executor and dev server).
e2e: demo-seed
	cd frontend && node e2e/demo.mjs

openapi:
	uv run python -m app.api.openapi

worker:
	uv run python -m app.executor --loop 30

scheduler:
	uv run arq app.scheduler.worker.WorkerSettings

demo-seed:
	uv run python -m bench.demo_seed

demo:
	uv run python -m bench.demo

demo-whatsapp:
	uv run python -m bench.demo_whatsapp

# --- the web platform (frontend/, Task 7) ---------------------------------------------------

web:
	cd frontend && npm run dev

web-install:
	cd frontend && npm ci

web-lint:
	cd frontend && npm run api:check && npm run typecheck && npm run lint

web-test:
	cd frontend && npm test

web-audit:
	cd frontend && npm audit --omit=dev --audit-level=low
