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
| `product_refund_rate_band` | refunds per order line over 14 days >= 1.5x the product's history since day 21 and conditional binomial p < 0.001, 3 days | profitability |
| `campaign_attribution_collapse` | attributed / promoted revenue <= 0.5x baseline over 14 days, promoted sales within 15%, the sales drop explains < 30% of the attributed drop, and that drop exceeds 2 sigma of promoted sales, 3 days | data quality |
| `campaign_incrementality` | attributed purchases +35% over 14 days vs the 28 before, promoted units within 10%, campaign active throughout, 5 days | profitability |

A campaign with an attribution collapse has its attributed-metric symptoms (CPA, campaign profit,
incrementality) re-classified as data quality: a tracking break is never a profitability alert.

All numbers live in `app/detection/thresholds_v1.toml` (versioned; the version is recorded in
every detection audit entry and benchmark report). They were tuned on the `dev` suite only.

## Consequences

- Every alert can be explained as "this metric moved this much against this baseline", with the
  facts to prove it.
- Statistical tests were chosen for the noise each signal has: robust z for step changes, CUSUM
  for slow drifts, a conditional binomial for small refund counts (plugging in a baseline rate
  estimated from a handful of refunds produced false alarms), Poisson residuals for purchases.
- Known blind spots (see the benchmark report): subtle drifts below the CUSUM allowance, refund
  spikes on small products (14-day windows plus refund lag delay detection by ~3 weeks), and a
  CPA drift on a campaign that is a small share of its products' sales, which is
  indistinguishable from a partial tracking break without order-level attribution.
- Any threshold change bumps the file version and must be re-tuned on `dev`, never on `test`.
