# ADR 0018: Outcome measurement

- Status: accepted
- Date: 2026-10-30

## Context

Each executed decision should be judged by what it earned, with an interval, or not judged at
all when the data cannot tell (SPEC section 7). A raw before/after confuses the action with
seasonality, trends and noise; on synthetic stores outcomes must exist after the action.

## Decision

**Outcomes exist**: for synthetic stores, the simulator lets the store live after the action
(ADR 0017), at least the observation window (default 7 days).

**Synthetic control** (`backend/app/causal/control.py`, `outcome.py`). Treated series: the acted
campaign's daily contribution after ads (its promoted products' contribution margin minus its
spend). Donors: every campaign sharing no product with it, and every product it does not
promote. The treated series is fitted, over the pre-period, as an intercept plus a convex
combination of donors (weights >= 0 summing to 1, projected gradient on demeaned series); after
the action the same combination is the counterfactual. Effect: actual minus counterfactual summed
over the window; interval: circular blocks of pre-period residuals of the window's length,
bootstrapped (2000, seeded), P10 / P50 / P90.

**Pre-period: the regime the action interrupts.** History is searched over the 84 days before
the action. When the treated series has a structural break in it (the largest mean shift, Welch
t >= 3, at least 7 days on each side) and at least two windows follow the break, the fit starts
at the break; it covers at most the last 42 days. A stockout is the typical case: the campaign
keeps spending on a product it can no longer sell, so its contribution drops to minus its spend.
Fitting across that break would compare the action with the store before the incident, not with
the incident continuing.

**Abstention**: when the window is not fully observed yet ("too little post-decision history"),
when there is no donor, when the pre-period is shorter than twice the window, or when the
pre-period fit is weak: its daily RMSE above half the series' mean absolute level. R-squared is
recorded but not used: a series that is flat after a break (spend only) has little variance to
explain even when the donors track it closely (the demo's pause, `bench/reports/demo-stockout.md`:
R-squared -0.06 at a relative error of 0.29, over 40 days). The first criterion was R-squared
below 0.3; it was replaced, and the 0.5 threshold chosen, after the demo stockout abstained on
it, so the threshold was set after seeing that case and is flagged for review. The decision
stays `executed` and can be measured again later.

**Records**: the effect is an `estimate` fact (`outcome.effect.contribution_after_ads`, campaign
scope, the window as period, method `synthetic_control_v1`) with the campaign's exact facts
(promoted contribution margin, ad spend) before and after as parents. The outcome row keeps the
twin's prediction for the same window, re-simulated as the twin saw the store when the decision
was proposed, so the trust ledger can compare them. A measured outcome moves the decision to
`measured`.

**Review answers** (`backend/app/agent/review.py`): the model explains the measured effect
against the prediction from facts only; with no measured outcome the answer abstains
(`abstain_insufficient_evidence`, added by code).

## Consequences

- An effect is never a raw difference, and a weak comparison says so instead of guessing.
- The window measures the campaign's own contribution; spillovers to other products are only
  captured if they show in the donors (they are excluded from the donor pool when promoted by the
  same campaign).
- On a 7-day window with daily noise, intervals are wide; the trust ledger needs many outcomes
  before it proposes anything. In the demo the pause measured 212 / 245 / 330 against a
  prediction of 281 / 296 / 311: the predicted median is inside the measured interval, but the
  measured median is below the predicted P10, so the ledger counts it as a miss.
