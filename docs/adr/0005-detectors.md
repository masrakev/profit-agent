# ADR 0005: Deterministic detectors first

- Status: accepted
- Date: 2026-10-27

## Context

The LLM investigator (Task 3) needs a baseline it must match or beat, and the product needs
alerts that are explainable and reproducible. Detection must also respect the core invariant:
whatever a symptom reports is a fact, never a number produced by a model or a heuristic.

## Decision

Detection is deterministic code over daily series aggregated in SQL (`app/detection/series.py`,
same definitions as the fact formulas). Each detector emits a `Finding` (when a condition first
held long enough, on which entity); the pipeline turns it into a `Symptom` by persisting the facts
behind it for the current window and the baseline window before it. Symptoms carry fact ids and
an internal ranking score, never amounts.

Statistical detectors run on **daily** values, which are close to independent day to day (an
earlier version on overlapping 7-day windows had baselines of ~4 independent values, a MAD that
underestimated noise, and false alarms on every healthy store):

| Detector | Signal | Test |
| --- | --- | --- |
| `campaign_cpa_z` | attributed purchases per unit of spend, down | robust z vs trailing 28 days |
| `campaign_cpa_cusum` | Poisson residual of purchases vs reference rate x spend | CUSUM |
| `product_units_z` | daily units, down (median >= 5/day) | robust z, threshold 4.0 |
| `product_unit_cost_z` | COGS / units, up | robust z, scale floor 1% |
| `product_unit_fee_z` | per-unit fees / units, up | robust z, scale floor 1% |
| `store_payment_fee_rate_z` / `_cusum` | payment fees / revenue, up | robust z; CUSUM (k 0.5, h 8) |
| `store_gross_margin_rate_z` / `_cusum` | (revenue - COGS) / revenue, down | robust z; CUSUM (k 0.25, h 12) |

Robust z: `(x - median) / max(1.4826 * MAD, rel_floor * |median|, abs_floor)` against the
trailing 28 days, |z| >= 3.5 on 3 consecutive days. CUSUM: one-sided, standardized against a
fixed 28-day reference period starting a week after the entity's first activity.

Business rules (from the task):

| Rule | Fires when | Category |
| --- | --- | --- |
| `campaign_profit_negative` | attributed contribution - spend < 0 over 14 days, 3 days | profitability |
| `product_cover_below_lead_time` | units on hand / (28-day units / 28) < supplier lead time, with promoting spend in the last 7 days, 4 days | profitability |
| `product_refund_rate_band` | refund events per exposed line over 14 days >= 1.5x the product's history since day 21 and conditional binomial p < 0.001 (BH-corrected), 3 days; exposure of a day = average lines sold 2-20 days before it (the refund lag) | profitability |
| `campaign_attribution_collapse` | a step down in attributed purchases per click (see below), clicks within 25%, promoted sales within 15%, the attributed drop beyond 2 sigma of promoted sales and real sales explaining at most 30% of it plus 1 sigma, 5 days | data quality |
| `campaign_incrementality` | attributed purchases +35% over 14 days vs the 28 before, promoted units within 10%, campaign active throughout, 5 days | profitability |

A campaign with an attribution collapse has its attributed-metric symptoms (CPA, campaign profit,
incrementality) re-classified as data quality: a tracking break is never a profitability alert.

### v1 revisions (Task 2b)

- **Multiple testing.** Per detector and per day, the p-values of all entities (two-sided normal
  tail of the robust z; conditional binomial for refunds) go through Benjamini-Hochberg at
  FDR q = 0.05 (`[multiple_testing]`). A day counts only if it passes both the threshold and BH;
  persistence rules then apply on top.
- **CPA drift vs tracking break by shape.** The change point of attributed purchases per click
  (the split with the largest two-sample z for a drop, using data up to each day) splits the
  history. Tracking break = a step: over the 5 days before the change point (skipping one day
  each side for location error) the rate is >= 75% of the baseline with >= 10 purchases, over
  the 5 days after it it is <= 50% of that, and clicks continue. A gradual decline, or real sales
  that follow the attributed drop, stays a CPA drift. The campaign CPA CUSUM uses k = 0.25.
- **Baselines end before the change point.** Symptoms with a change point (CUSUM start, collapse
  step) take their baseline window before it, so the fault does not leak into the baseline.
- **Grouping.** A store-level symptom joins an incident only when a product symptom in it can
  explain it (gross margin rate by a unit cost change); otherwise it is its own incident. When
  a promoted product is out of stock, the CPA, campaign profit and units symptoms it causes vote
  for the stockout (at half weight) instead of a CPA drift.
- **Out of stock.** The cover rule notes when stock is zero on the confirmation day; promoting
  spend on an out-of-stock product is a critical alert (ADR 0008).

All numbers live in `app/detection/thresholds_v1.toml` (versioned; the version is recorded in
every detection audit entry and benchmark report). They were tuned on the `dev` suite only.

## Consequences

- Every alert can be explained as "this metric moved this much against this baseline", with the
  facts to prove it.
- Statistical tests were chosen for the noise each signal has: robust z for step changes, CUSUM
  for slow drifts, a conditional binomial for small refund counts (plugging in a baseline rate
  estimated from a handful of refunds produced false alarms), Poisson residuals for purchases.
- Known blind spots (see the benchmark report): subtle drifts below the CUSUM allowance; refund
  spikes on products with a high base refund rate, where the expanding baseline also absorbs
  the post-fault days; store-level margin CUSUMs that fire on healthy demand drift and outrank
  the real incident; and a step-like CPA drift on a campaign that is a small share of its
  products' sales, which is indistinguishable from a partial tracking break without order-level
  attribution. When ambiguous, the rule reads it as data quality, the safer error: it blocks
  spend actions instead of recommending them.
- Any threshold change bumps the file version and must be re-tuned on `dev`, never on `test_v2`.
