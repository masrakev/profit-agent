# ADR 0012: The agent as an auditor of the pipeline

- Status: accepted
- Date: 2026-10-29

## Context

The deterministic pipeline (ADRs 0005-0008) detects incidents and ranks candidate causes. Its
known weaknesses are structural: windows that straddle the fault start, a baseline that already
contains the fault, product sums that do not match store totals, ad platforms that over-report
purchases, rankings that flip when a window moves by a week. An investigator that only repeats
the ranking adds cost without value; one that free-styles adds risk (invented numbers, invented
causes, confident errors). SPEC section 15 asks the agent to cross-examine the pipeline, and to
say how sure it is, without ever changing what the pipeline computes.

## Decision

**Three read-only audit tools** (`backend/app/agent/tools/audit.py`), next to the lookup tools of
ADR 0010:

- `run_sensitivity(incident_id)` recomputes the incident's attribution, expected impact and
  candidate ranking under a fixed, versioned set of window variants (`sensitivity_v1`: reference,
  baseline shifted 7 days either way, fixed windows of 14, 28 and 42 days). `stable` is computed
  by code: the same top cause and the same impact sign in every valid variant; otherwise
  `unstable_because` names the variants that disagree.
- `check_reconciliation(scope, period)` compares product sums with store totals for revenue,
  COGS, fees, refunds and contribution margin, and platform-attributed purchases with real orders
  of the promoted products, as derived gap facts with lineage.
- `get_method(fact_id | incident_id)` returns how a fact or an incident was computed: formula,
  windows, thresholds and their versions.

They persist derived facts like any tool; none of them can change a formula, a threshold or a
setting, and no tool that writes business data exists (ADR 0010).

**Rules enforced in code, not in the prompt** (`investigator.py`):

1. Every investigation must call `run_sensitivity` for its incident. If the model answers
   without it, it is reminded once; if it still does not, code runs the check and the
   investigation is stored as `invalid` (its hypotheses are kept for inspection, not shown as a
   conclusion).
2. If the code-computed verdict is unstable, every hypothesis is capped at `medium` confidence,
   the `low_evidence` flag is added, and an `unstable_conclusion` audit finding is added if the
   model did not report one. Each adjustment is recorded on the investigation.
3. Audit findings are typed (`unstable_conclusion`, `window_contamination`,
   `reconciliation_gap`, `data_gap`, `weak_evidence`, `method_mismatch`), cite fact ids, and go
   through the verifier like every other output.
4. The agent never changes the pipeline. Patterns where investigations overturned the
   detectors are written by the benchmark runner to `bench/reports/audit_proposals.md`, from
   `dev` runs only, for a human to review; a detector change is then tuned on `dev` and evaluated
   on a new hold-out suite (ADR 0007).

**Ranking.** The investigator may re-rank the deterministic candidates and must say which tests
it ran for each hypothesis. Its top hypothesis is what the benchmark's agent arm scores; the
pipeline's incident, alert level and impact are unchanged by an investigation.

## Consequences

- Robustness is checked on 100% of investigations by construction (target of SPEC section 12),
  and the benchmark reports how often the model itself called the check.
- Confidence becomes measurable: the benchmark reports accuracy per confidence level and the
  share of confident errors; the cap turns unstable "high" conclusions into "medium" ones.
- The sensitivity check costs extra pipeline computations per investigation (six variants) and
  one or two tool calls; it is memoised within an investigation.
- Audit findings are proposals, never automatic changes: a wrong finding costs a human review,
  not a wrong formula in production.
- The variant set is fixed and versioned; changing it changes `stable` verdicts and must bump
  `SENSITIVITY_VERSION`.
