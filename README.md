# Verifiable Profit Agent

An AI profit analyst for e-commerce stores: it finds where a store loses money, proves it with
verifiable numbers, acts with the owner's approval, and measures what each decision earned.

> General agents tell you what to do. Ours proves why, simulates before acting, and measures what
> it earned.

Built for the Meta Global AI Developer Hackathon (Startup track).

What the product does, for whom, and its settings and alerting rules: see the
[product specification](docs/product/SPEC.md).

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
uv run python -m app.detection.pipeline --store <store_id>   # symptoms, incidents, attribution
make test
make lint
make eval                                 # detection benchmark (test_v3 suite), ~5 minutes
make api                                  # HTTP API on http://127.0.0.1:8000 (/docs)
make demo                                 # the stockout loop: alert -> approval -> action -> outcome
make smoke-live                           # one live call per Meta model (needs MODEL_API_KEY)
```

The benchmark's agent arm investigates each primary incident with a live model:
`uv run python -m bench.runner --suite dev --agent --routing economy` (Contributor model on
synthetic stores; `--routing production` for Spark and Wonder). The golden questions run with
`uv run python -m bench.golden.runner --routing economy|production`.

The twin's interval calibration is rebuilt with `uv run python -m bench.twin.calibrate` (dev
suite; `--check` reports the coverage of the frozen calibration), and the options on the golden
scenarios with `uv run python -m bench.twin.options_report`.

Model calls run in `replay` mode by default (committed cassettes, no key, no network); set
`LLM_MODE=live` or `record` and `MODEL_API_KEY` in `.env` to call the Meta Model API. Spending
caps per run, per day and in total are enforced before every call (see `.env.example`).

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
| `make eval` | `uv run python -m bench.runner` (test_v3 suite; writes `bench/reports/`) |
| `make eval-dev` | `uv run python -m bench.runner --suite dev` (tuning suite) |
| `make scenarios` | `uv run python -m bench.scenarios.build` (rebuild scenario manifests) |
| `make smoke-live` | `uv run python scripts/smoke_live.py` (`--mode record` writes cassettes) |
| `make api` | `uv run uvicorn app.api.main:app --app-dir backend` |
| `make worker` | `uv run python -m app.executor --loop 30` (the outbox worker) |
| `make demo` | `uv run python -m bench.demo` (writes `bench/reports/demo-stockout.md`) |

The compose stack publishes PostgreSQL on port 55432 and Redis on 56379 to avoid clashing with
local installs (`POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` override them).

## Layout

```
backend/app/
  domain/         Pydantic models, SQL schema, repositories, hash-chained audit log
  facts/          fact engine: formula registry, SQL aggregations, lineage, recompute CLI
  verifier/       render {{F<id>}} references; reject unreferenced numbers
  detection/      daily series, detectors, versioned thresholds, incidents, materiality, pipeline
  causes/         exact two-level Shapley attribution of net profit changes, noise bands
  agent/          model layer (Meta Responses provider, guards, record/replay), read-only
                  lookup and audit tools, output guard, versioned prompts, stage config and
                  routing, investigator, Ask
  twin/           store twin: response curves, Monte Carlo against doing nothing, calibration
  decisions/      options by cause, verdicts, decisions and approvals, signed links, journal
  policies/       policy engine (kill switches, autonomy, caps), trust ledger
  executor/       outbox worker, Meta Marketing API and simulator adapters, rollback
  causal/         outcome measurement with synthetic control
  api/            FastAPI: Ask, investigate an incident, read an investigation (/api/v1)
  channels/       per-channel rendering of merchant text (HTML escaping, plain text)
  settings/       per-store settings (SPEC section 4) with defaults and audited saves
  observability/  structlog JSON logging
backend/migrations/  Alembic (schema, row-level security, grants)
backend/tests/       golden, property-based, RLS, audit and red-team tests; model cassettes
bench/generator/     deterministic synthetic store generator
bench/faults/        fault catalogue and non-fault conditions with ground-truth labels
bench/scenarios/     committed scenario manifests (dev, test_v3, golden) and their builder
bench/golden/        golden question set, its checks and runner, pending scenarios
bench/runner/        benchmark runner, scoring, agent arm, reports, audit proposals
bench/twin/          twin calibration on dev scenarios, options report on golden scenarios
bench/simulator.py   synthetic stores that live day by day, with the owner's actions applied
bench/demo.py        the demo loop on the golden stockout store
bench/reports/       committed benchmark reports (latest.md = test_v3 suite)
docs/adr/            architecture decision records
docs/product/        product specification
scripts/             live smoke test of the Meta models
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
- **Day 2 - faults, detection, attribution, benchmark**
  - Eight fault types (CPA drift, cannibalization, stockout on a promoted product, supplier cost
    increase, refund spike, mix shift, fee increase, tracking break) as pure, seeded
    transformations with ground-truth labels; 50-scenario test suite and 30-scenario dev suite.
  - New facts: campaign profit, MER, attribution ratio, refund rate (golden tests).
  - Detectors: robust z-scores and CUSUMs on daily series, business rules (negative campaign
    profit, cover below lead time, refund rate, attribution collapse as data quality,
    incrementality); every symptom backed by persisted facts; thresholds in one versioned file.
  - Incidents grouping symptoms over the entity graph, with ranked root-cause candidates.
  - Exact two-level Shapley attribution of net profit changes, stored as facts with lineage.
  - Benchmark runner with top-1/top-3 accuracy, detection rate and delay, false alerts,
    attribution check and runtime; reports in `bench/reports/`. ADRs 0005-0007.
- **Day 2 - precision and product spec**
  - Product specification and golden question set.
  - Per-store settings (materiality, alert budget, quiet hours, schedules, autonomy, spending
    caps) with row-level security, defaults and audited saves.
  - Economic materiality: expected monthly impact of each incident (P10/P50/P90 by block
    bootstrap over Shapley contributions); alerts gated on absolute and relative thresholds,
    with critical / high / normal levels and a watchlist. ADR 0008.
  - Benjamini-Hochberg correction across entities; noise bands marking significant profit
    drivers; CPA drift told from a tracking break by the shape of the change; baselines that end
    before the change point.
  - Benchmark protocol v2: larger dev suite, a fresh `test_v2` hold-out run once, golden
    scenarios, alert precision and alerts per healthy store-month.
- **Day 3-4 - model layer, tools and safety**
  - One `LLMProvider` interface and its Meta Model API implementation (Responses API through the
    OpenAI SDK): strict tool calling and JSON-schema structured output from Pydantic models,
    explicit reasoning effort, stateless conversations (`store: false`), prompt cache keys.
  - Contributor mode only for synthetic benchmark stores; a versioned price table and exact cost
    per call; budget guard (per run, per day, total) checked before each call; retries with
    backoff and jitter; circuit breaker; an OpenTelemetry span per call.
  - Live, record and replay modes with committed cassettes; CI replays only. A live smoke script
    per model.
  - Nine read-only, typed tools whose numbers are all facts; `compute` over facts without
    literal numbers; a write guard on the tools' connection.
  - Store text as escaped data blocks; versioned static prompts; an output guard (verifier,
    known facts and entities only, two regenerations, then a deterministic answer); entity
    references in model text. Red-team suite: 0 unsafe outcomes. ADRs 0009-0010.
- **Day 4 - investigator, auditor, Ask and the agent benchmark**
  - Severity relative to the store: critical at 10% and high at 5% of the trailing-30-day
    contribution margin, on top of the absolute floor; merchant names escaped per channel (HTML
    for email and web, plain text for WhatsApp).
  - Investigator agent: one tool loop with a cache-friendly prefix, verified and audited output,
    a deterministic fallback, partial results on budget exhaustion; Wonder only for ambiguous
    incidents (data-quality doubt, close scores, conflicting symptoms).
  - Audit tools (`run_sensitivity`, `check_reconciliation`, `get_method`) with rules enforced in
    code: a robustness check on every investigation, confidence capped when unstable, detector
    proposals for human review only.
  - Per-stage model config, compact tool results, memoised calls, an investigation cache keyed
    on fact hashes, prompt, model and config versions; per-stage token and cost reports, repriced
    at Standard prices.
  - Ask: question classification, lookup, explain, diagnose (grounded in investigations), improve
    and data questions; FastAPI endpoints under `/api/v1`. Golden question runner and checks.
  - Red team against the real models (Spark, Wonder), recorded: 0 unsafe outcomes, 0 unverified
    numbers.
  - Benchmark protocol v3: `test_v2` into dev, a fresh `test_v3` hold-out, an agent arm next to
    the deterministic baseline. Results and misses in `bench/reports/agent-report.md`.
    ADRs 0011-0013.
- **Day 5 - twin, options and what-if**
  - Owner actions applied by the generator from a given day (budget change, pause), so simulated
    actions can be compared with real outcomes.
  - Store twin: per-campaign response curves with a seeded bootstrap, organic demand, unit
    economics, stock, a price-elasticity prior; Monte Carlo against doing nothing with the same
    draws; results as estimate facts with lineage. Split-conformal calibration on dev, frozen:
    P10-P90 coverage 78% on held-out dev scenarios, 74% on the test_v3 hold-out (target
    75-85%). ADR 0014.
  - Options generated by code per cause, simulated, with risks, reversibility and invalidation
    conditions; a recommendation rule and a go / adjust / avoid verdict rule decided by code.
    ADR 0015.
  - Ask answers evaluate and what-if questions (intent parsed into a typed scenario, ask back
    when ambiguous) and ranks simulated options in improve answers. Golden evaluate and what-if
    questions are active.
- **Day 6 - decisions, policy, execution and outcomes**
  - Decisions with a state machine enforced by the database, one approval per decision, approval
    and outbox rows in one transaction; email approval links signed, single use, 24 hours.
  - Policy engine (kill switches, autonomy, +-30% cap, one change per campaign per day,
    reversibility), every evaluation audited; a trust ledger that only proposes promotions.
  - Outbox worker with SKIP LOCKED, dry run, read-back, idempotency and crash recovery; Meta
    Marketing API adapter (sandbox, tested against the documented contract) and a simulator;
    rollback.
  - Outcomes measured by synthetic control, or abstention; review answers; the stockout demo
    loop end to end. Action red team: 0 duplicate executions, 0 actions outside policy.
    ADRs 0016-0018.
  - Citations enforced in code: an answer that names a metric cites a fact of it.
