# ADR 0015: Options and verdicts

- Status: accepted
- Date: 2026-10-29

## Context

The owner needs to know what to do about a cause, and whether a change they have in mind is
worth it. Letting a model propose actions or judge them invites invented options, invented
numbers and overconfident verdicts. SPEC sections 7 and 8 ask for 2-3 options with ranges,
risks, reversibility and invalidation conditions, and for evaluate answers with a verdict
(`go`, `adjust`, `avoid`) and a better alternative.

## Decision

**Options come from a fixed catalogue per cause** (`backend/app/decisions/options.py`):

| Cause | Options |
| --- | --- |
| CPA drift, negative campaign profit | budget -20%, -30%, pause |
| Cannibalization | budget -20%, -30%, pause (flagged for an incrementality test), the test |
| Underfunded profitable campaign | budget +10%, +20% (capped at +-30% by policy at execution) |
| Stockout on a promoted product | pause the promoting campaigns for the supplier lead time, budget -30% for that time, prepare a reorder |
| Supplier cost increase | prepare a +5% price change, review the supplier |
| Refund spike | investigate product quality (no automated action) |
| Tracking break | fix tracking (no budget action) |
| Fee increase, mix shift (store-wide) | monitor |

Each option that changes something is simulated by the twin (ADR 0014) against doing nothing
and carries its net-profit change range, risks, reversibility (reversible, prepare only,
manual, none) and invalidation conditions.

**Recommendation rule** (floor = the store's monthly absolute materiality scaled to the
horizon): among simulated options whose net-profit change has P10 >= -floor and P50 > 0, the
best P50; if none, the cause's manual step (investigate quality, fix tracking, incrementality
test); otherwise monitor. Requiring P50 > 0 extends the task's rule ("best P50 among options
whose P10 is not worse than doing nothing by more than the floor"): an option that loses money
at the median is never recommended.

**Verdict rule** for an owner's intent (`backend/app/decisions/verdict.py`): the intent and its
variants (the same change at other sizes, or for half the time) are simulated; a scenario is
*good* when P10 >= -floor and P50 > 0.

- go: the intent is good and no good variant beats its P50 by more than the floor;
- adjust: a good variant exists and the intent is not good, or the variant beats it by more
  than the floor; the answer recommends that variant;
- avoid: no version of the change is good;
- no verdict when the twin cannot simulate the intent (the answer abstains).

**Ask** (`backend/app/agent/evaluate.py`): the intent stage (Spark, structured output) parses
the owner's words into action, entity, size and duration, and asks back when one is missing or
ambiguous; code resolves "my best-selling product", simulates, and decides the verdict; the model
only explains, from the parameters, the simulated changes and the entity's current facts, and
must cite the net-profit change and at least one current fact. Improve answers rank the options
of the investigated causes, then capped budget increases that the rule recommends, each with its
simulated range (`backend/app/agent/opportunities.py`).

## Consequences

- No option, number or verdict comes from the model; the model can only choose the words, and
  the verifier checks every number is a fact.
- The rules are deterministic and testable; changing a catalogue entry or a threshold is a code
  change reviewed like any other.
- Conservative by construction: with calibrated (wide) ranges, large changes often fail the
  P10 test and the rule prefers the smaller variant (for example budget -20% over -30% on the
  golden CPA drift).
- The catalogue covers only the causes the detectors find; store-wide causes get "monitor" until
  options exist for them (payment fees, pricing review).
