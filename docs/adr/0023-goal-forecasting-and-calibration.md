# ADR 0023: Goal forecasting and calibration

- Status: accepted, amended 2026-10-31 (goals beyond 90 days; the time of year, a known
  limitation)
- Date: 2026-10-31

## Context

An owner states a goal ("60,000 in net profit by the end of March"); the product must say
whether it is reachable, with a probability computed by code and never written by a model
(SPEC 17.2). A probability is only worth showing if it is calibrated: of the goals given 70%,
about 70% should be reached. The quality bar (SPEC 17.6) is P10-P90 coverage of 75-85% at 30,
60, 90 and 180 days, a reliability curve within 10 points per bucket, and a Brier score better
than a naive baseline, measured by backtests on stores the method was not tuned on. The
benchmark stores had 120 days of data, too short for 180-day horizons.

## Decision

**Long histories** (`bench/generator`, `LongHistory`). Stores of up to 400 days whose market
grows or shrinks at a rate that drifts slowly, with a yearly cycle and occasional regime
changes; off by default, drawn from a random stream of its own and left out of serialized
configs, so every existing manifest rebuilds byte for byte. Two suites with fresh seeds:
`goals_dev` (tuning) and `goals_test` (run once): 42 stores each, growing, flat and declining,
each trend with 6 healthy stores and one clear fault per type in the second half of the history.

**Forecast** (`backend/app/goals/forecast.py`). The metric's daily values (net profit,
contribution margin or revenue, by the fact formulas' definitions) over the last 56 days are
fitted by least squares: level, trend and day of week. Ahead, the trend's daily growth halves
every 60 days. 2,000 seeded paths: each draw refits the model on the fitted values plus
residuals resampled in weekly moving blocks (the trend's uncertainty carried forward), then
adds future residuals in blocks; the cumulative sums are the paths. A structural time-series
model (local linear trend with seasonal components, statsmodels) was the alternative: it assumes
Gaussian disturbances, and its long-horizon intervals rest on the variance of a trend it cannot
estimate well from a few months; the bootstrap keeps the residuals' own distribution and
autocorrelation, costs milliseconds, and both would need the same empirical calibration. No
yearly seasonality: with at most 400 days of history (often 150 at the cut), a yearly cycle
cannot be told apart from a trend.

The fit window and the damping were chosen on `goals_dev` by two-fold cross-validation over
stores (`bench/reports/goals-backtest-dev.md`): among 13 settings, the lowest cross-validated
Brier score whose cross-validated coverage stayed within 75-85% at every horizon. Long windows
were much worse (182 days, linear: Brier 0.207 against 0.120): a store's level moves, and old
data drags the trend.

**Calibration.** The raw intervals are too narrow (45-63% coverage on `goals_dev`): residual
blocks do not anticipate regime changes or a drifting growth rate. Per metric and horizon bucket
(30, 60, 90, 180 days), a split-conformal factor: the score of a backtest forecast is how far
the outcome fell from the median, in units of the side of the interval it fell on; the factor is
its quantile at rank ceil((n + 1) x 0.8). Each day's deviations from the median path are scaled
by the factor of its horizon (interpolated between buckets), so the whole distribution, and the
probability with it, is calibrated, not only the interval. Factors range from 1.53 (net profit,
30 days) to 2.98 (revenue, 180 days). They are frozen in `backend/app/goals/calibration.json`
with the settings they were fitted with; a cell the cross-validation finds poorly calibrated
(coverage out of 75-85%, or a reliability curve more than 10 points off on average) is listed
there.

**Probability, verdict, gap** (`backend/app/goals/feasibility.py`). The probability is the share
of calibrated paths that reach the target at the deadline, with an interval from a bootstrap
over the draws; the verdict follows SPEC 17.2 (`likely` 70% or more, `possible` 40-70%, `stretch`
15-40%, `unlikely` under 15%); the gap is the target minus the forecast at the deadline.
`low_evidence`, with its reasons, when the horizon is longer than the store's history or its
cell is listed as poorly calibrated. All of it is stored as `estimate` facts with the fit
window's exact fact as parent: the cumulative forecast for every day to the deadline, the
probability and the gap.

**Beyond 90 days** (amended 2026-10-31, after the backtest; SPEC 17.2, rule 6). No point
probability is shown for a goal past 90 days. Its probability is an interval of 15 points either
side of the share of paths (the larger of the two backtests' mean reliability errors at 180
days), with the verdict band its two ends give, `low_evidence` and the reason. The probability
fact carries that interval, so a cited probability renders as a range. Such a goal is split into
quarterly checkpoints, every 90 days to the deadline, each with its forecast range; its plan is
detailed and simulated for the first 90 days only (ADR 0024), and its forecast is redone every
month by the scheduler.

**Backtest** (`bench/goals_backtest.py`). Histories cut at days 150, 190, 230, 270, 310 and 350;
each metric forecast at each horizon the data reaches. Goals: nine targets per forecast, from
40% below to 40% above the store's run rate at the cut. The task asked for targets around the
true outcome; that would decide whether each target is reached by construction (a target set at
the outcome minus a margin is always reached), and a well-calibrated forecast would look
miscalibrated. Targets are set from what the owner knows at the cut instead. The naive baseline
is the last 28 days' mean times the horizon, with a normal spread.

## Consequences

- On the `goals_test` hold-out, run once (`bench/reports/goals-backtest.md`): coverage 81%,
  80% and 80% at 30, 60 and 90 days, 89% at 180 days (too wide, outside 75-85%); reliability
  within 4.2 points in every bucket; Brier 0.121 against 0.159 for the naive run rate (skill
  0.24). On `goals_dev`, in sample: coverage 80% at every horizon, reliability within 3.3
  points, Brier 0.120 against 0.156.
- 180-day forecasts are overconfident, on both suites: their reliability is 13 (dev) and 15
  (test) points off on average, predicted 60-70% reached about a third of the time, although
  their intervals are wide enough. They come from the two earliest cuts only, both in the same
  season, and the history is too short for a yearly cycle. Goals over more than 90 days carry
  `low_evidence` and show a probability range, never a point; the pooled reliability, dominated
  by shorter horizons, does not show this.
- Calibration widens the raw intervals 1.5 to 3 times: the honest uncertainty of a store's
  profit months ahead is wide, and the verdict says so.
- Calibrated on average over the year, not at every time of year (found 2026-10-31 by the
  plan validation, ADR 0024). Per cut, at 60 days, the share of outcomes above the calibrated
  70th percentile (expected 30%) is 2%, 14%, 42%, 56% and 60% at days 150, 190, 230, 270 and
  310 of `goals_test` (8% to 60% on `goals_dev`). The suites' stores all peak on the same day of
  the year (the generator's default) and the forecast has no yearly term: a forecast made while
  the season falls extrapolates the fall, one made at the trough misses the rise, and every
  store errs the same way at the same cut. The pooled reliability averages these out. A real
  store with a season would see the same. Not fixed here: a yearly term needs more than a year
  of history; the options are a seasonal prior by category, a yearly term once a store has two
  years, and suites whose stores peak on different days. Until then (2026-11-01), a forecast
  from less than a year of history is `low_evidence` with the reason "yearly seasonality not
  learned", on every goal answer and plan.
- The benchmark stores grow and shift by the generator's own rules; a real store's trend can
  change for reasons none of this models. The backtest on real stores' histories is the next
  check, with the design partners.
