# ADR 0014: Store twin and interval calibration

- Status: accepted
- Date: 2026-10-29

## Context

Options and the owner's "what if" questions need a predicted effect with a range, against what
would happen anyway, and the range has to mean what it says: P10-P90 should contain the outcome
about 80% of the time (SPEC section 12: 75-85%). Stores have a few months of daily data, a
handful of campaigns whose daily spend moves little, and list prices that rarely change.

## Decision

**A structural twin fitted on the last 42 days** (`backend/app/twin/`), as of any date:

- *Ad response* per campaign: `purchases = a * (1 - exp(-b * spend))` on the platform's daily
  attributed purchases, least squares profiled over a grid of `b` (half saturation between
  about 3.5 and 700 per day of spend) with `a` in closed form; 500 seeded bootstrap resamples of
  days give the parameter uncertainty. Campaigns with fewer than 14 days of spend get no curve
  (budget actions on them are not simulated).
- *Platform over-attribution*: real ad-driven purchases are attributed purchases divided by a
  factor drawn uniformly from [0.8, 2.0] per simulation draw (twin v2). Below 1, platforms miss
  conversions (cross-device journeys, browser privacy limits); up to 2, they also credit buyers
  who would have bought anyway. Field experiments comparing platform attribution with randomized
  lift find attribution overstating incremental effects, often by a wide margin (Gordon,
  Zettelmeyer, Bhargava and Chapsky, Marketing Science 2019; Blake, Nosko and Tadelis,
  Econometrica 2015). The range is chosen from that evidence and is independent of the benchmark
  generator (twin v1 used the generator's own range, 0.9-1.35: a leak, replaced). A store with an
  incrementality test would use its measured factor instead.
- *Organic demand* per product: the observed rate (Gamma posterior) minus its ad-driven part,
  Poisson around it; ad-driven purchases are spread evenly over a campaign's promoted products.
- *Unit economics* from the same daily series as the exact facts: net price, unit cost of the
  last 14 days, fees per unit, refunds as a share of revenue.
- *Stock*: units sold cannot exceed stock on hand plus arrivals at the window's arrival rate.
- *Price response*: own-price elasticity estimated (log-log on daily units) only when two list
  prices at least 5% apart were each sold on 7 days or more; otherwise a uniform prior on
  [-3, -0.5], and every answer resting on it carries `low_evidence`.
- *Fixed costs* continue at their daily rate.

**Monte Carlo against doing nothing.** 1000 draws over the horizon (14 days by default, up to
60); every scenario (budget change, pause, all ad spend, price change, new campaign, each for a
number of days) and "do nothing" are simulated with the same draws, so their difference is the
action's effect. Outputs: P10/P50/P90 of contribution margin, net profit, units and ad spend for
the scenario, for doing nothing and for the difference, persisted as `estimate` facts
(`twin.*`, `twin.do_nothing.*`, `twin.change.*`) with the fit window's exact facts as parents.
The scenario's parameters are exact `twin.parameter.*` facts, so answers cite them. Spend outside
the range a curve was fitted on, a borrowed curve (new campaign) and the price prior are
reported as weak evidence.

**Split-conformal calibration on dev, frozen** (`bench/twin/calibrate.py`,
`backend/app/twin/calibration.toml`). For each dev scenario the twin is fitted 14 days before
the data end and predicts those days for four versions of the same store: doing nothing, and
the generator really applying a budget -30%, +20% or a pause to the largest campaign from that
day (`bench.generator.Intervention`). Even-index scenarios set one factor `q` per metric and per
kind (doing nothing, action): the conformal quantile of `max(P10 - y, y - P90) / half-width` at
80%. An interval becomes `[P10 - q w, P90 + q w]`; a difference is widened by the larger factor,
never narrowed. Calibration v2 (twin v2, the independent over-attribution prior), on the 77
held-out dev scenarios: coverage 77% raw, 78% calibrated; per metric 77-80%; per variant doing
nothing 78%, budget -30% 80%, budget +20% 86% (above the target band), pause 70% (below it).
One factor serves every action kind, so pauses are under-covered and increases over-covered; a
factor per action kind is the obvious next step. (Calibration v1, fitted with the generator's
own over-attribution range, had 79% overall and pause 75%.) The factors were frozen before any
hold-out use; their version is part of every simulated fact.

**Hold-out check** (`--check --suite test_v3`, once, nothing refitted): on the 70 `test_v3`
scenarios (1120 intervals) the frozen calibration v2 covers 74% (raw 75%), just below the
target band; doing nothing 72% (contribution margin and net profit 67%: the dev factors narrowed
them more than the hold-out supports), budget -30% 80%, budget +20% 82%, pause 63%.

## Consequences

- Every range the product shows for an action has been checked against real outcomes of that
  kind of action, in the synthetic world, and the check is reproducible.
- Price changes cannot be calibrated here: the generator's demand ignores price. Price answers
  rest on the prior and say so; a real store with price history would estimate the elasticity.
- Cannibalization is invisible to the twin: it treats attributed purchases (after the
  over-attribution factor) as incremental, so cutting a cannibalizing campaign looks like a
  loss. The options for that cause include an incrementality test.
- Daily spend varies little (about 15% around the budget in the bench world), so curves are
  weakly identified and most budget changes are extrapolations, flagged as such; the bootstrap
  and the calibration make the ranges honest rather than narrow.
- The calibration encodes the bench world's assumptions; on real stores it has to be redone on
  their own history (the same runner, with recorded actions instead of interventions).
