# Verifiable Profit Agent

An AI profit analyst for e-commerce stores: it finds where a store loses money, proves it with
verifiable numbers, acts with the owner's approval, and measures what each decision earned.

> General agents tell you what to do. Ours proves why, simulates before acting, and measures what
> it earned.

Built for the Meta Global AI Developer Hackathon (Startup track).

## Principles

- **No number comes from an LLM.** Every number is a `Fact` computed by deterministic code and
  stored with its formula, version, inputs hash and lineage. Model text references facts as
  `{{F<id>}}`; a verifier rejects any other literal number.
- **Exact money.** `NUMERIC(18,4)` + ISO 4217 currency in PostgreSQL, `Decimal` in Python,
  accounting facts aggregated in SQL. Rounding only at presentation (half-even).
- **Tenant isolation** by PostgreSQL row-level security, tested.
- **Determinism.** Seeded generators; recomputing a fact over the same inputs gives the same hash.

## Quick start

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Docker, GNU make.

```bash
cp .env.example .env
make up                                   # PostgreSQL 16 + Redis, then migrations
uv run python -m bench.generator --seed 42
uv run python -m app.facts.recompute --store <store_id printed above>
make test
make lint
```

### Run without make

Each Makefile target runs these commands:

| Target | Commands |
| --- | --- |
| `make up` | `docker compose up -d --wait` then `uv run alembic upgrade head` |
| `make down` | `docker compose down` |
| `make migrate` | `uv run alembic upgrade head` |
| `make test` | `uv run pytest` |
| `make lint` | `uv run ruff check .` then `uv run ruff format --check .` then `uv run mypy` |
| `make format` | `uv run ruff check --fix .` then `uv run ruff format .` |
| `make eval` | placeholder until the evaluation suite lands (prints a message) |

The compose stack publishes PostgreSQL on port 55432 and Redis on 56379 to avoid clashing with
local installs (`POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` override them).

## Layout

```
backend/app/
  domain/         Pydantic models, SQL schema, repositories, hash-chained audit log
  facts/          fact engine: formula registry, SQL aggregations, lineage, recompute CLI
  verifier/       render {{F<id>}} references; reject unreferenced numbers
  observability/  structlog JSON logging
backend/migrations/  Alembic (schema, row-level security, grants)
backend/tests/       golden, property-based, RLS and audit tests
bench/generator/     deterministic synthetic store generator
docs/adr/            architecture decision records
```

## Built during the hackathon

Everything in this repository was built during the event (Oct 26 - Nov 4, 2026).

- **Day 2 - backend foundations**
  - Project scaffold: uv, ruff, mypy (strict), pytest + hypothesis, Docker Compose, Makefile,
    GitHub Actions (lint, types, tests against PostgreSQL, gitleaks, pip-audit).
  - Domain schema for stores, products, orders, order lines (with cost snapshots at sale), refunds,
    inventory, ad campaigns and daily metrics, fixed costs, facts, lineage and audit log.
  - Row-level security on every table, a non-superuser application role, composite tenant
    foreign keys; append-only facts and audit log; SHA-256 hash-chained audit log with verifier.
  - Fact engine: 24 versioned formulas (revenue to net profit, ROAS/POAS/CPA, inventory cover)
    with exact SQL aggregation, undefined-with-reason on zero denominators, lineage and
    reproducible hashes; golden tests matched to the cent.
  - Numeric grounding verifier (amounts, percentages, ratios, multiplicative claims, spelled-out
    numbers) with adversarial and property-based tests.
  - Deterministic synthetic store generator (seasonality, saturating ad response, refunds,
    inventory with supplier lead times) and a `Fault` protocol for fault injection.
  - ADRs 0001-0004.


- Never push. The human reviews and pushes every commit.
- Commit messages contain no Co-Authored-By trailer and no AI attribution of any kind.
