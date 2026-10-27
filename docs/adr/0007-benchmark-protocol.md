# ADR 0007: Benchmark protocol

- Status: accepted
- Date: 2026-10-27

## Context

Detection and root-cause ranking need a measurable, reproducible score, both to improve the
deterministic pipeline and to judge the LLM investigator (Task 3) against it. Tuning on the same
scenarios we report would overstate quality.

## Decision

**Scenarios.** A scenario is a generator config + seed + faults + ground-truth labels, committed
as JSON in `bench/scenarios/<suite>/` (generated data is not committed). Bench stores are healthy
by construction: no natural supplier cost changes, stock planned for ad demand and reordered at
three lead times, campaigns budgeted below their profit optimum. Each fault is a pure, seeded
transformation with a label (fault type, acceptable root-cause entities, start day, magnitude,
category, expected profit driver).

**Split.** `test` (reported): 5 scenarios per fault type (one deliberately subtle, the rest of
increasing strength) + 10 healthy = 50. `dev` (tuning only): 3 per fault type (subtle, medium,
strong) + 6 healthy = 30. Seeds never overlap. `python -m bench.scenarios.build --check` verifies
the committed manifests equal a fresh deterministic build. Thresholds are tuned on `dev`; the
`test` suite is run once thresholds are frozen and reported as is.

**Scoring** (`bench/runner/score.py`):

- Primary incident: the most severe incident of the scenario (any category).
- Correct root cause: candidate fault family = label fault type **and** candidate entity is one
  of the label's entities (stockout: the product or its campaign; store faults: the store).
- Top-1 / top-3: on the primary incident's ranked candidates. A scenario without incidents
  counts as wrong.
- Detected: some symptom on a label entity (a store-level symptom for store faults) first seen
  no earlier than 3 days before the fault start. Delay = first seen - start (floored at 0).
- False alert (healthy scenarios): any profitability incident. Data-quality incidents are
  reported but do not count.
- Tracking break correctly classified: a data-quality incident on the campaign and no
  profitability incident involving it.
- Attribution check: the label's expected driver is the largest negative level-1 contributor of
  the attribution the pipeline computed (tracking breaks have none and are excluded).
- Runtime: wall time per scenario (generate, load through the app repositories, run detection)
  and for the whole suite, with 4 worker processes.

**Outputs.** `make eval` runs the `test` suite on a fresh `profit_bench` database and writes
`bench/reports/<timestamp>-test.json` (every scenario, incident, candidate and attribution) and
`bench/reports/latest.md`; `make eval-dev` writes `latest-dev.md`. Reports are committed.

## Consequences

- Results are reproducible bit for bit, except runtimes.
- Five scenarios per fault type give coarse per-type rates (steps of 20%); the overall numbers
  are the meaningful ones. Growing the suites is cheap.
- The synthetic world encodes our assumptions (e.g. platform over-attribution of 0.9-1.35x);
  the benchmark measures the pipeline against those assumptions, not against real stores.
