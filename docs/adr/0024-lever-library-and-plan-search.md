# ADR 0024: The lever library and the plan search

- Status: accepted
- Date: 2026-10-31

## Context

Once a goal is confirmed and its feasibility known (ADR 0023), the owner can ask for a plan: dated
steps from levers that are known to move the metric, the probability with the plan and without
it, weekly milestones to follow it by, and, for a goal still out of reach, what is reachable
instead (SPEC 17.3). Code decides every step and every number; the model explains. A plan never
executes anything: its steps become decisions that go through the policy engine and the owner's
approval like any other. The quality bar (SPEC 17.6) asks for the plan's uplift, the success rate
with the plan against without, measured on simulator ground truth with an interval.

## Decision

**Levers are code** (`backend/app/goals/levers.py`). Each lever has a name, its mechanism, its
preconditions read from facts over the last 28 days, and the steps it proposes, each with the
twin actions the plan builder simulates. A step is a `decision` (executable through the normal
flow), a `manual` step the owner does (a reorder) or an `experiment`.

| Lever | Mechanism | Preconditions | Step |
| --- | --- | --- | --- |
| `reallocate_budget` | budget moves from a campaign whose ads cost more than they earn to one whose ads earn more than they cost | a campaign with negative campaign profit, and one with positive campaign profit and a fitted response curve | lower the loser by the budget cap, raise the winner by the same amount (within the cap) |
| `scale_profitable` | more budget on a profitable campaign buys more profitable sales, until the response curve flattens | positive campaign profit, a fitted curve, and a positive marginal profit for the next increase in the twin; for a revenue goal, any campaign with a curve, while the next increase brings more in sales than it costs in ads | raise by 10, 20 or 30% (within the cap), the last step whose marginal gain is positive |
| `prevent_stockout` | sales a product would lose when it runs out are kept by reordering in time | the product sells, has a positive contribution margin, the store does not keep it supplied (no stock arrived in six weeks or two lead times), and its stock covers less than its lead time and the horizon | a manual reorder, dated to arrive when the stock would run out (now, if that is already too late) |
| `cut_unsellable_spend` | ads for products that cannot be sold spend money for nothing | a campaign promotes a product with no stock on hand and none arriving | pause the campaign |
| `shift_to_margin` | the same ad spend earns more on products with a higher margin | two campaigns with fitted curves whose promoted products' margin rates are above 1.25 and below 0.75 times the median | move budget from the low-margin campaign to the high-margin one, within the cap |

Experiments are listed with every plan and never counted in its probability until measured:

| Experiment | Mechanism | Precondition | Cap | Duration | Success | Measurement |
| --- | --- | --- | --- | --- | --- | --- |
| `price_test` | a price never changed may be below what buyers would pay | a product with stock whose price never changed enough to estimate its elasticity (the best seller) | one product, at most 5% above its price | 14 days | its contribution margin above what synthetic control expects | synthetic control, as for every decision |
| `refund_reduction` | a product refunded far more than the rest often has a fixable cause | a product refunded at least twice as often as the store | one product | 28 days | its refund rate falls by a third against the store's | refund rate before and after, against the other products |
| `creative_refresh` | a campaign whose cost per purchase keeps rising often has a tired creative | cost per purchase over the last 14 days 15% above the 14 before | one campaign, budget unchanged | 14 days | cost per purchase a tenth lower than synthetic control expects | synthetic control |

Considered: letting the model propose steps from the facts. Its steps could not be simulated
consistently, their preconditions could not be audited, and a step the data does not support
would read as advice; the model explains the steps code chose.

**The twin simulates the steps** (`backend/app/twin`). Plans needed three extensions of the twin
of ADR 0014: scenarios up to 90 days; actions that start on a later day (`start`) and a restock
action (a reorder arriving after the supplier's lead time); and `change_draws`, the scenario
minus doing nothing on the same draws, widened by the twin's change calibration. Revenue is in
the twin's totals for revenue goals (it has no calibration of its own; its spread is the
simulation's). The baseline forecast already contains the store's usual reorders, so every plan
simulation assumes them too (the products the store keeps supplied, with or without the plan):
a reorder step counts only the sales the store would otherwise lose.

**Probability with the plan.** The plan's change, draw by draw, is added to the baseline
forecast's calibrated paths (ADR 0023): the share of the sums that reach the target is the
probability with the plan, with the same bootstrap interval as without. The baseline is the
feasibility's own forecast (the same seed), so the probability without the plan is the one the
owner was shown.

**The search** (`backend/app/goals/plan.py`) is greedy with re-simulation. From no step, each
round tries every remaining decision or manual step that touches no campaign already changed
(one change per campaign), simulating all the chosen actions together, so interacting steps are
judged together; the step that raises the probability most is kept, or, when nothing moves the
probability (a goal far out of reach or already sure), the one that raises the median outcome
most. A step is kept only if the plan's P10 stays within the materiality floor (scaled to the
plan's days) of the baseline's P10: a plan may not risk much more than it can gain. It stops when
no step improves the plan, or after five steps. Considered: an exhaustive search over subsets
(2^n simulations of 2,000 draws for a dozen candidates, minutes per plan, for interactions the
re-simulation already captures), and a continuous budget optimizer (the curves are fitted on the
spend the store had; beyond it the twin extrapolates, and an owner approves 10, 20 or 30%, not
an optimum to the cent).

**What a plan holds.** Its dated steps, each with its own simulated effect (P10-P90); weekly
milestones, the cumulative metric with the plan, each week simulated on its own; the probability
without and with; the outcome at the deadline; the plan's effect on net profit; the experiments;
the assumptions (campaigns keep their recent spend scaled by any change, reorders arrive after
the lead time, the store's trend and noise follow the forecast, steps run only once approved).
When the goal stays `unlikely` with the plan: the targets reached with 50% and 70% probability
(each a bootstrap range), the first deadline within six months that makes the target `possible`,
and the experiments. A revenue plan that lowers net profit says so first, in code's words, before
anything the model writes.

**Beyond 90 days** (SPEC 17.2, rule 6). The plan is detailed and simulated for the first 90 days
only; the goal's quarterly checkpoints and the monthly re-forecast take over from there.

**Records and the flow** (`backend/app/goals/service.py`, migration 0014). Goals (a draft until the
owner confirms the restated goal), plans (proposed, accepted, superseded), steps and progress, all
under row-level security; every number is a fact. Accepting a plan proposes its decision steps
whose day has come as decisions (source `goal`); later steps are proposed by the weekly tracking
when their day comes. Weekly tracking: the actual so far against the last milestone (`ahead`,
`on_track`, `behind`), the steps executed, and the probability of what is left; a revision is
proposed when the actual is outside the milestone band two weeks in a row or the verdict drops a
level, never applied by itself. Every month the forecast is redone. Both are scheduler jobs, and
the weekly report shows each planned goal's progress.

**Ask** (`backend/app/agent/goal.py`). A `goal` question is parsed (intent stage, structured
output) into a metric, a target and a deadline; anything missing or ambiguous is asked back, never
guessed. Code saves a draft and restates it citing the target fact; once the owner confirms, code
computes the feasibility or builds the plan and the model explains it from the facts only. The
answer must cite the probability and state code's verdict word, or code writes it from the same
facts. Past a quarter the probability is a range and the answer is flagged `low_evidence`.

## Validation

Plans followed in the simulator (`bench/goals_plans.py`): on each store of a suite, at days
150, 230 and 310, a goal on net profit and one on revenue for the next 60 days, at the 70th
percentile of the forecast from that day (reached about three times in ten without a plan). The
plan is built as in production; its budget and pause steps are executed in the simulator from
their day, generating the same store again with them, and the outcome compared with the store
without the plan. Reorders are not executed (the simulator's restock only ends a stockout
fault); no plan of these suites had one.

| | `goals_dev` | `goals_test` (hold-out, once) |
| --- | --- | --- |
| Goals (with steps) | 252 (246) | 252 (244) |
| Reached without the plan, predicted | 37%, 30% | 35%, 30% |
| Reached with the plan, predicted | 43%, 36% | 39%, 36% |
| Uplift (90% interval over stores) | +6.0 points (+2.0 to +9.9) | +4.8 points (+2.0 to +7.5) |
| Net profit goals / revenue goals | +4.8 / +7.1 points | +5.6 / +4.0 points |
| Milestone weeks inside the P10-P90 band | 83% | 81% |
| Outcomes inside their P10-P90 | 77% | 76% |
| Effect on net profit, predicted / realised (mean) | 1,883 / 3,059 | 2,007 / 2,315 (1,096 to 3,535) |

(`bench/reports/goals-plans-dev.md`, `bench/reports/goals-plans.md`.) The plans raise the chance of
reaching a goal by about five points, as the twin predicts, and the realised effect on net profit
is at least the predicted one. The milestones hold the realised path about 80% of the time, as a
P10-P90 band should; the outcome at the deadline a little less (76-77%). Almost every plan scales
profitable campaigns: the benchmark stores' budgets are set below their most profitable spend
(`profit_optimal`), so that is the lever their data supports; reallocation, cutting unsellable
spend and the margin shift appear in a handful of plans, and no reorder (their stores reorder in
time). A first `goals_dev` run with goals set at days 250 and 310 only had them reached 60% of
the time against 30% predicted: the forecast errs one way at one time of year (ADR 0023, known
limitation), so goals are set across the yearly cycle. The hold-out ran once; two of its 42
stores were finished by `--resume` after the database stalled under the run (an autovacuum caught
between two loads' statistics refreshes; the bench databases now run without autovacuum).

## Consequences

- An owner sees why each step is there (its lever, its facts) and what it is worth (its range),
  and can follow the plan week by week; nothing changes in the store until a step is approved.
- Plans are only as good as the twin: campaigns' response curves are fitted on the spend they
  had, so a budget far above it is an extrapolation (flagged by the twin), and reorders are not
  validated by the simulator (its restock only ends a stockout fault).
- The probability with the plan assumes every step is approved on its day. The weekly tracking's
  probability is the forecast of what is left from the latest data: a step not yet executed
  counts for nothing there, so a plan whose steps wait for approval reads as a verdict drop and
  proposes a revision.
- New levers are code: a lever needs its preconditions as facts and its effect as twin actions.
