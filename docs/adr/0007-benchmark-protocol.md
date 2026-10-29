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

**Split (protocol v2).** Once the v1 `test` results had been read, `test` was no longer a clean
hold-out for the next threshold version, so it was merged into `dev`.

| Suite | Use | Content |
| --- | --- | --- |
| `dev` | tuning | former dev (3 per fault type) + former test (5 per fault type) + 20 healthy = 84 |
| `test_v2` | reported once, after freezing | 5 per fault type (one subtle) + 30 healthy = 70, fresh seeds |
| `golden` | demo and product tests | `healthy-a`, `healthy-b`, one strong scenario per fault type, `golden-underfunded_campaign`, `golden-injection` |

**Split (protocol v3, Task 3 part B).** The `test_v2` results were read in Task 2b, so `test_v2`
joined `dev` (same seeds, renumbered ids) and a new hold-out took its place:

| Suite | Use | Content |
| --- | --- | --- |
| `dev` | tuning (detectors, prompts, routing) | v2 dev (84) + former `test_v2` (70) = 104 faulty + 50 healthy = 154 |
| `test_v3` | reported once, after freezing prompts and routing | same composition as `test_v2`, fresh seeds = 70 |
| `golden` | demo, product tests, golden questions | unchanged |

Seeds never overlap. Golden scenarios also carry *conditions* that are not faults (an
underfunded campaign; an instruction injected in a product description), labelled for later
tasks; scenarios the golden question set references but that need decisions are listed in
`bench/golden/pending.yaml`, and a test checks that every reference resolves.
`python -m bench.scenarios.build --check` verifies the committed manifests equal a fresh
deterministic build.

**Scoring** (`bench/runner/score.py`; v2 changes are marked):

- Alerts (v2): profitability incidents at level critical, high or normal, plus data-quality
  incidents. Watchlist incidents (below materiality, ADR 0008) are not alerts.
- Primary incident (v2): the first incident as the owner sees them (alert level, then expected
  monthly loss, then statistical severity).
- Correct root cause: candidate fault family = label fault type **and** candidate entity is one
  of the label's entities (stockout: the product or its campaign; store faults: the store).
- Top-1 / top-3: on the primary incident's ranked candidates. A scenario without incidents
  counts as wrong.
- Detected: some symptom on a label entity (a store-level symptom for store faults) first seen
  no earlier than 3 days before the fault start. Delay = first seen - start (floored at 0).
- False alert (v2, healthy scenarios): any profitability **alert**. Watchlist items and
  data-quality incidents are reported but do not count.
- Tracking break correctly classified: a data-quality incident on the campaign and no
  profitability alert involving it.
- Attribution check: the label's expected driver is the largest negative level-1 contributor of
  the attribution the pipeline computed (tracking breaks have none and are excluded). v2 also
  reports whether that driver's contribution is significant (outside its noise band).
- New metrics (v2): alert precision (alerts involving a label entity, first seen no earlier than
  the grace before the fault; every alert on a healthy store is wrong), profitability alerts per
  healthy store per month, incidents by level, and materiality-gated incidents per scenario.
- Runtime: wall time per scenario (generate, load through the app repositories, run detection)
  and for the whole suite, with up to 8 worker processes.
- Level-2 attribution check (v3): the expected driver is also checked against the largest
  negative contributor *within the incident's scope* (the product or campaign the incident is
  about), not only store-wide.

**Agent arm (v3).** `--agent --routing economy|production` investigates each scenario's primary
incident with the live investigator (ADR 0012) next to the deterministic baseline. The
investigation never changes alerts, so false alerts stay the pipeline's. Scored per scenario and
per fault type: agent top-1 and top-3 (same rule as the baseline, on the ranked hypotheses),
tracking breaks read as data quality, confident errors (wrong top-1 at high confidence, over
faulty scenarios), top-1 accuracy per confidence level, unstable conclusions, robustness-check
coverage, wrong conclusions whose confidence the audit capped, top-1 changes that helped or hurt,
share escalated to Wonder, verifier violations (final and rejected), cost per investigation
(actual and repriced at Standard prices), latency, and tokens per stage with the cache hit rate.
Dev agent runs also write `bench/reports/audit_proposals.md` (SPEC section 15): patterns where
investigations overturned the detectors, for human review only.

**Outputs.** `make eval` runs the `test_v3` suite on a fresh `profit_bench` database and writes
`bench/reports/<timestamp>-test_v3.json` (every scenario, incident, candidate, impact,
attribution and, with `--agent`, investigation) and `bench/reports/latest.md`; `make eval-dev`
writes `latest-dev.md`. Reports are committed; earlier reports stay in the history.

## Consequences

- Results are reproducible bit for bit, except runtimes.
- Five scenarios per fault type give coarse per-type rates (steps of 20%); the overall numbers
  are the meaningful ones. Growing the suites is cheap.
- A hold-out suite is spent once results are read: the next threshold, prompt or routing
  version needs a new hold-out suite with fresh seeds, never re-tuning against the old one
  (`test_v2` is now dev; `test_v3` is next).
- Agent runs are live and cost money; their results vary between runs (model sampling), so a
  single `test_v3` agent run is reported as is, with its spend.
- The synthetic world encodes our assumptions (e.g. platform over-attribution of 0.9-1.35x);
  the benchmark measures the pipeline against those assumptions, not against real stores.
