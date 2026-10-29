# ADR 0011: Model routing

- Status: accepted
- Date: 2026-10-29

## Context

Three models are available through the Meta Model API (ADR 0009): Muse Spark 1.3 (Standard
mode), the same model in Contributor mode (about 10-20x cheaper, but the content may be used for
training), and Muse Wonder 1.0 (stronger, 3-5x the price of Spark). The agent has four kinds of
work with very different needs: classifying an owner's question, answering a lookup question,
investigating an incident, and investigating an ambiguous one. Merchant data must never reach a
model that may train on it. The benchmark needs hundreds of investigations, which at Standard
prices would exceed the Part B budget.

## Decision

**Stages.** Each kind of work is a stage with its own model, reasoning effort and limits, in
`backend/app/agent/stages.toml` (ADR 0013):

| Stage | Model (production) | Effort | Used for |
| --- | --- | --- | --- |
| classification | Spark | low | question type of an Ask request; no tools |
| lookup | Spark | low | Ask answers (diagnose, explain, list, lookup) |
| investigation | Spark | medium | an incident with a clear deterministic ranking |
| escalation | Wonder | high | an ambiguous incident |

**Escalation to Wonder** is decided by code, from the incident alone, before any model call
(`routing_decision` in `investigator.py`):

- data-quality doubt: the incident, or any of its symptoms, is in the data-quality category;
- close scores: the two best candidates are different families and the second scores at least
  80% of the first (or the first is not positive);
- conflicting symptoms: at least two detectors fired and fewer than half of them support the top
  candidate.

Otherwise the investigation stage runs ("clear deterministic ranking"). The reason is stored
with the investigation and reported.

**Routings.** `production` uses each stage's model. `economy` uses Spark Contributor for every
stage, at the stage's effort, and is accepted only for synthetic stores
(`StagesConfig.route` raises otherwise; the provider also refuses Contributor for real data,
ADR 0009). The benchmark's dev and `test_v3` agent runs use economy routing; golden scenarios are
also run once with production routing to measure the realistic cost, Wonder escalations
included. Ask classification uses economy routing automatically on synthetic stores
(SPEC section 16).

**Cost reporting.** Every result records the model used. Reports give the actual cost and the
cost repriced at Standard prices (Contributor calls repriced at Spark). Under economy routing an
escalated investigation runs on Spark Contributor, so its Standard repricing is a Spark price,
not a Wonder one: the production-routing golden run is the figure to use for production cost.

## Consequences

- Most investigations stay on Spark; Wonder is paid for only where the deterministic ranking is
  in doubt. The escalation share is a benchmark metric.
- Economy benchmark runs measure the prompts, tools and audit rules with a weaker-priced but
  same-capability model; they do not measure Wonder's added accuracy on escalated incidents.
- Routing rules are deterministic and testable without a model; changing them is a stage-config
  or code change, never a model decision.
- Thresholds (80%, half of the detectors) were set by judgement, not tuned; they can be tuned on
  `dev` like any other parameter.
