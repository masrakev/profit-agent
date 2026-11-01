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
make up                                   # PostgreSQL 16, Redis, Mailpit, then migrations
uv run python -m bench.generator --seed 42
uv run python -m app.facts.recompute --store <store_id printed above>
uv run python -m app.detection.pipeline --store <store_id>   # symptoms, incidents, attribution
make test
make lint
make eval                                 # detection benchmark (test_v3 suite), ~5 minutes
make api                                  # HTTP API on http://127.0.0.1:8000 (/docs)
make demo-seed                            # the demo store: history, alert, investigation, briefings
make demo                                 # the stockout loop: alert -> approval -> action -> outcome
make scheduler                            # briefings, detection and alerts, email (arq + Redis)
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
| `make scheduler` | `uv run arq app.scheduler.worker.WorkerSettings` (cron jobs) |
| `make openapi` | `uv run python -m app.api.openapi` (writes the frozen contract `docs/api/openapi.json`) |
| `make demo-seed` | `uv run python -m bench.demo_seed` (a fresh `profit_demo` database with the demo store) |
| `make demo` | `uv run python -m bench.demo` (seeds the demo store, runs the loop; writes `bench/reports/demo-stockout.md`) |

The compose stack publishes PostgreSQL on port 55432 and Redis on 56379 to avoid clashing with
local installs (`POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` override them), and Mailpit, which
receives every email locally: SMTP on 1025, its inbox on http://localhost:8025. Briefing costs
are measured with `uv run python -m bench.briefing_costs` (live, golden scenarios).

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
  causal/         outcome measurement with synthetic control, intervals calibrated per action
  briefings/      daily brief, weekly report, monthly review from facts; alert and decision
                  messages; the model's short narrative, or facts only
  delivery/       alerts (severity, quiet hours, budget, deduplication), deliveries, worker
  scheduler/      arq cron jobs per store time zone: briefings, detection, deliveries
  api/            FastAPI (/api/v1): every store route the web platform reads and acts through,
                  problem details, request ids, rate limits, security headers, frozen contract
  auth/           owners, email sign-in links, sessions, per-store API tokens
  privacy/        export, deletion, trace retention, encrypted platform tokens
  goals/          forecasts to a deadline, the probability of reaching a target, its verdict;
                  the lever library, plans, tracking and re-forecasts
  channels/       per-channel rendering of merchant text; email (SMTP) and its templates
  settings/       per-store settings (SPEC section 4) with defaults and audited saves
  observability/  structlog JSON logging
backend/migrations/  Alembic (schema, row-level security, grants)
backend/tests/       golden, property-based, RLS, audit and red-team tests; model cassettes
bench/generator/     deterministic synthetic store generator
bench/faults/        fault catalogue and non-fault conditions with ground-truth labels
bench/scenarios/     committed scenario manifests (dev, test_v3, golden, outcomes_v1, goals_dev,
                     goals_test) and their builder
bench/golden/        golden question set, its checks and runner, pending scenarios
bench/runner/        benchmark runner, scoring, agent arm, reports, audit proposals
bench/twin/          twin calibration on dev scenarios, options report on golden scenarios
bench/simulator.py   synthetic stores that live day by day, with the owner's actions applied
bench/demo_seed.py   the demo store: the golden stockout store with a history (make demo-seed)
bench/demo.py        the demo loop on the seeded store
bench/outcome_validation.py   outcome intervals against the truth (the store without the action)
bench/outcome_calibration.py  the outcome intervals' conformal widening, fitted on dev
bench/unit_economics.py       unit economics from measured costs
bench/citation_attach.py      golden questions before and after attaching citations in code
bench/goals_backtest.py       goal forecasts and probabilities against what happened
bench/goals_plans.py          goal plans followed in the simulator, against the same store without
bench/briefing_costs.py  what briefings cost, measured live on the golden scenarios
bench/reports/       committed benchmark reports (latest.md = test_v3 suite)
docs/adr/            architecture decision records
docs/api/            the API contract (openapi.json) and its conventions
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
  - Golden questions, all 30 active: 73% with production routing and 80% with economy routing,
    below the 90% target (`bench/reports/golden-latest-*.md`).
- **Day 7 - briefings, alerts and email**
  - Daily brief, weekly report and monthly review assembled by code from facts (SPEC 5.1-5.3),
    "Nothing needs your attention today" when nothing is material; Spark writes only a short
    narrative, verified, and the briefing goes out from facts only when it fails twice.
  - Alerts after each detection run: critical at once, others after quiet hours and within the
    daily budget, deferred to the next brief over it; one alert per incident and level; a
    decision with simulated options for each profitability alert. ADR 0019.
  - Delivery records per message and channel; email through SMTP (Mailpit locally, any
    provider's relay), HTML and text templates with every merchant string escaped, golden
    snapshots; a worker with SKIP LOCKED, retries with backoff and a circuit breaker.
  - arq cron jobs in each store's time zone: briefings, detection and alerts, deliveries.
  - Email approval links: opening one no longer decides (mail scanners open links); the
    confirmation page posts it.
  - Briefing costs measured on the golden scenarios: about USD 0.007 a daily brief, 0.014 a
    weekly report and 0.014 a monthly review (`bench/reports/briefing-costs.md`).
- **Day 8 - the backend, complete**
  - Owners sign in by email link (single use, 15 minutes) into HTTP-only session cookies with
    CSRF; programs use per-store API tokens; every store route answers only the caller's
    stores (404 otherwise), tested route by route. ADR 0020.
  - The API the web platform is built on, frozen in `docs/api/openapi.json` (a test checks it):
    overview, incidents, investigations with their step trace streamed, facts with formula and
    lineage, the profit bridge, decisions, journal, briefings, Ask streamed, settings, kill
    switch; problem details, request ids, cursor pagination, rate limits, security headers.
  - Privacy: export everything a store has; delete all of it, with a test that finds no row
    left in any tenant table and the deletion recorded outside the store's data; model traces
    kept 30 days; Meta and Shopify tokens encrypted at rest (AES-256-GCM envelope). ADR 0021.
  - Briefings show losses as positive amounts after the word "lost", never "lost -$..."; a
    narrative longer than three sentences is rewritten once, then cut at a sentence end.
  - The fact of a metric an answer names is attached in code instead of regenerating: 21
    citations in 14 answers over three golden runs; the pass rate moved from 77.8% to 78.9%,
    within the spread of three runs (`bench/reports/citation-attach.md`). ADR 0022.
  - Outcome intervals checked against the truth (the same store without the action): 66% on
    dev, too narrow; a split-conformal widening per action kind fitted on dev, frozen, then
    validated once on 70 fresh stores: 82% (target 80%). ADR 0018.
  - Unit economics from measured costs: USD 5.81 a month for a typical store at USD 49 (88%
    gross margin), 82% in the worst measured case (`bench/reports/unit-economics.md`).
  - A demo store with a history (`make demo-seed`): past decisions measured, the stockout
    alert and its pending decision, an investigation, briefings; `make demo` runs the loop on
    it.
- **Day 9 - goals: forecast and probability (Task 6 part A)**
  - Long store histories in the generator (up to 400 days: drifting growth, a yearly cycle,
    regime changes), off by default so every existing scenario rebuilds byte for byte; two
    suites of 42 growing, flat and declining stores, `goals_dev` and `goals_test`.
  - A metric's forecast to a deadline (net profit, contribution margin or revenue): least
    squares on the last 8 weeks with a damped trend and the day of week, 2,000 block-bootstrap
    paths, calibrated per horizon by split conformal on `goals_dev` and frozen. The probability
    of reaching a target, its verdict (likely, possible, stretch, unlikely), the gap and
    `low_evidence`, all estimate facts. ADR 0023.
  - Backtest on the `goals_test` hold-out, run once: coverage 80-81% to 90 days, 89% at 180;
    reliability within 4.2 points; Brier 0.121 against 0.159 for the naive run rate. 180-day
    probabilities are overconfident and flagged low evidence
    (`bench/reports/goals-backtest.md`).
- **Day 10 - goals: plans, Ask and tracking (Task 6 part B)**
  - Beyond 90 days a goal shows no point probability: the verdict band and a probability range,
    flagged low evidence, with quarterly checkpoints; its plan is detailed for the first 90
    days and its forecast redone every month (SPEC 17.2, ADR 0023).
  - A lever library in code (budget reallocation, scaling a profitable campaign, reorders before
    a stockout, cutting spend on products that cannot sell, shifting spend to higher margins)
    and three experiments that are never counted until measured. A greedy plan search with
    re-simulation in the twin, one change per campaign and a downside limit; weekly milestones,
    the probability with and without the plan, and for a goal still unlikely the targets and the
    deadline within reach. ADR 0024.
  - Goals, plans, steps and progress in the database and the API (`/goals`): a goal is a draft
    until the owner confirms its restatement; accepting a plan turns its due steps into
    decisions to approve; weekly tracking proposes a revision, never applies one; the weekly
    report shows each goal's progress.
  - Ask takes goals: parsed, restated for confirmation, asked back when incomplete, then the
    feasibility or the plan explained from facts; a revenue plan that lowers net profit says
    so first, in code's words. Six golden goal questions pass, on a new golden store whose
    campaigns spend past their most profitable budget.
  - Plans followed in the simulator against the same store without them, on the `goals_test`
    hold-out, run once: the success rate rises by 4.8 points (90% interval 2.0 to 7.5 over
    stores; the twin predicted about 6), 81% of milestone weeks inside their P10-P90 bands, the
    realised effect on net profit at least the predicted one (`bench/reports/goals-plans.md`).
  - The plan validation also showed that goal forecasts are calibrated over the year, not at
    each time of year (no yearly term; the suites' stores peak on the same day): recorded in
    ADR 0023 as a known limitation.
  - The demo store (`make demo-seed`) has a 90-day goal with its plan accepted and two weeks of
    tracking.
- **Day 11 - backend complete: conflicts, approvals and seasonality**
  - Two pending decisions never act on the same campaign or product: the one resting on the
    most recent data stands, the other is `superseded` (a terminal state, linked to the one
    that stood, with the reason) and cannot be approved; a superseded goal step makes its plan
    propose a revision. In the demo, the stockout pause supersedes the goal's budget
    reallocation step on the same campaign. ADR 0016, amended.
  - Goal tracking tells "behind" from "waiting for approval": while the plan's due steps wait
    for the owner, the week is `waiting_for_approval`, with a prompt to approve in the weekly
    report, never a verdict drop or a revision.
  - Every goal answer and plan on a store with less than a year of history carries
    `low_evidence` with the reason "yearly seasonality not learned" (ADR 0023's time-of-year
    limitation, also listed in `docs/launch-readiness.md`).
