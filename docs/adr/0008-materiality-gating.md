# ADR 0008: Gate alerts on economic materiality

- Status: accepted
- Date: 2026-10-27

## Context

A statistically real change is not always worth the owner's attention. On the v1 benchmark most
incidents were real but small, and the product promises few, important alerts (SPEC section 6:
an alert budget per day, quiet hours, and a materiality threshold the owner can change). The
detectors answer "did something change?"; the alert decision must also answer "is it worth
money?", with an uncertainty the owner can read.

## Decision

**Settings.** Every setting of SPEC section 4 lives in a `store_settings` row per store (RLS,
audited saves, defaults when absent): materiality absolute 100 (store currency) and relative
3%, alert budget, quiet hours, schedules, channels, autonomy per action type, spending caps.
Detectors and alerting read thresholds from there; statistical thresholds stay in the versioned
`thresholds_v1.toml`.

**Expected monthly impact** (`app/detection/impact.py`, an `estimate` fact with P10/P50/P90,
method `block_bootstrap_shapley_v1`, parents = the incident's symptom facts):

1. Windows: the attribution windows of the incident (equal length, whole weeks; the baseline
   ends 7 days before the incident was first seen).
2. Scope: the incident's products, the products its campaigns promote, and its campaigns. A
   store-only incident uses the drivers its symptoms implicate across every product (payment fee
   rate: fees; gross margin rate: mix, price, unit cost). When an incident also names products or
   campaigns, store-wide drivers are dropped: those entities explain the store symptom.
3. Point value: the sum of the scope's level-2 Shapley contributions (volume, mix, price, unit
   cost, fees, refunds, ad spend; not fixed costs), current vs baseline, times 30 / window days.
4. Uncertainty: a seeded circular block bootstrap (7-day blocks, resampled within each window,
   500 resamples, resample 0 = observed data) repeating the vectorized decomposition. The seed
   derives from the store, first-seen day and entities, so reruns give the same fact hash.

**Gate and severity** (P50 loss = max(-P50, 0)):

| Level | Rule |
| --- | --- |
| critical | promoting spend on a product at zero stock, or material and loss >= 10 x absolute |
| high | material and loss >= 3 x absolute |
| normal | material: loss >= absolute **and** loss >= relative x trailing 30-day contribution margin |
| watchlist | anything else (kept, shown on request, never pushed) |
| data quality | data-quality incidents bypass the gate (a broken pixel is urgent at any size) |

Incidents are ordered by level (critical, high, data quality, normal, watchlist), then loss,
then statistical severity. The first profitability incident gets the full attribution and noise
band.

**Noise band.** Each level-1 `profit_driver` fact carries `significant`: whether its contribution
lies outside the P5-P95 band of the same driver's contribution between pairs of equal-length
windows of the store's own history before the baseline (adjacent pairs stepping by a week; a
7-day block bootstrap when fewer than 20 pairs exist).

## Consequences

- Owners get alerts with a money range attached, and small real changes go to a watchlist
  rather than disappearing.
- The relative threshold dominates on stores of the benchmark's size (30-day contribution margin
  of 76k-158k, so 3% is 2.3k-4.7k a month), and almost every material incident is above
  10 x 100: in practice "material" and "critical" coincide. The absolute default may need to
  scale with store size; this is a product decision (flagged for review).
- The impact is the observed change of the incident's entities, not a causal estimate: a
  coincident demand swing on the same products is counted. The bootstrap range shows sampling
  noise only.
- Severity is a formula change and a safety rule: any change goes through human review.
