# ADR 0006: Two-level Shapley attribution of profit changes

- Status: accepted
- Date: 2026-10-27

## Context

"Net profit fell" is not actionable; "unit cost of product X explains most of the drop" is. The
split must be fair (no arbitrary order of drivers), exact (contributions add up to the change to
the cent) and stored as verifiable facts.

## Decision

Net profit over a period is written with eight driver factors:

```
NP = sum_p Q * s_p * (P_p - C_p - F_p) - sum_p R_p - sum_c A_c - K
```

| Driver | Factor | Definition |
| --- | --- | --- |
| volume | Q | total units sold |
| mix | s_p | product share of units, q_p / Q |
| price | P_p | net revenue per unit, revenue_p / q_p |
| unit cost | C_p | COGS per unit, cogs_p / q_p |
| fees | F_p | (per-unit + allocated payment) fees per unit, fees_p / q_p |
| refunds | R_p | refunds of the product (by refund date) |
| ad spend | A_c | spend of the campaign |
| fixed costs | K | prorated fixed costs |

With every factor at its current value this equals the `net_profit` fact exactly (checked on
every run). A per-unit factor of a product that sold nothing in one period takes the other
period's value; it multiplies zero units, so the period's profit is unchanged and no driver gets
a spurious contribution.

Shapley value of driver i: the average of its marginal effect over all orders of switching
drivers from baseline to current values, computed by exact enumeration.

- **Level 1**: the product term is a sum of per-product games of five players (volume, mix,
  price, unit cost, fees); refunds, ad spend and fixed costs are additive. Shapley values are
  linear in the game, so level 1 = the sum over products of the per-product Shapley values, plus
  the additive changes. A test checks this equals brute-force enumeration of the full 8-player
  game.
- **Level 2**: the per-product (and per-campaign) values themselves. They sum exactly to their
  level-1 driver, and only 5 players are ever enumerated (32 coalitions per product).

Arithmetic is exact rationals (`fractions.Fraction`), because Shapley weights and per-unit
ratios are rational; `Decimal` would round in the weights. Results are converted to `Decimal`
once, on a grid of 1e-10 (or finer if the change itself has more digits), with largest-remainder
rounding that preserves sums exactly at both levels and never moves an exact zero.

Stored facts (`kind = exact`, `method = shapley_v1`, `period` = current, `baseline` = baseline):
`profit_delta`; `profit_driver.<driver>` at store scope (parents: its level-2 facts) and at
product or campaign scope (parents: the input facts of both periods).

Windows: whole weeks so weekly seasonality cancels. With an incident, the baseline ends a week
before it was first seen and the current window ends with the data (both 14-42 days); otherwise
the last two adjacent windows. Adjacent windows around an incident were tried first and diluted
the effect (the baseline already contained part of the fault).

## Guarantees (property-tested with hypothesis)

- Efficiency: level-1 contributions sum exactly to the change; level-2 sums exactly to level 1.
- Symmetry: interchangeable drivers get equal values (exact, before rounding).
- Null player: a driver whose factors did not change gets exactly zero, before and after rounding.

## Consequences

- Attribution is exact and reproducible, but it explains the change between two windows, not
  causality: random volume and refund fluctuations between windows are attributed too. When a
  fault's effect is small relative to that noise, the fault's driver is not the largest negative
  one (see the benchmark's attribution check).
- Rounding to the grid can break symmetry by at most one grid unit (1e-10); efficiency and null
  player hold exactly after rounding.
- Facts gained an optional `baseline` period (migration 0002); facts without one keep their
  original hashes.
