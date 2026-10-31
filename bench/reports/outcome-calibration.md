# Outcome calibration

Fitted by `uv run python -m bench.outcome_calibration` on 462 dev decision scenarios (`outcome-validation-dev-pause-20261031T011442Z`, `outcome-validation-dev-cut-20261031T011001Z`, `outcome-validation-dev-raise-20261031T011130Z`): every dev store, each action executed 14 days before the data end and measured after 7 days, against the same store without the action. Frozen in `backend/app/causal/outcome_calibration.json` (`conformal-v1`) before the validation on fresh scenarios.

Score of a reported estimate: max(P10 - truth, truth - P90) / (P90 - P10). Widening: the split-conformal quantile of the scores, rank ceil((n + 1) x 0.8), never negative; the interval becomes [P10 - q w, P90 + q w], the median unchanged.

| Action kind | Reported estimates | Coverage before | Widening q | Interval width x | Coverage after (in sample) | Median score |
| --- | --- | --- | --- | --- | --- | --- |
| increase_budget | 142 | 67% | 0.1962 | 1.39 | 81% | -0.160 |
| pause_campaign | 142 | 64% | 0.1984 | 1.40 | 81% | -0.194 |
| reduce_budget | 142 | 68% | 0.2147 | 1.43 | 81% | -0.186 |

In-sample coverage is at least the target by construction; what the widening is worth is measured once, on fresh stores (`bench/reports/outcome-validation-fresh.md`). A kind with no fit (a resume) gets the widest widening.
