# Twin calibration (`test_v3`)

Run 2026-10-30T03:05:02+00:00 - calibration v2 (split_conformal_v1) - horizon 14 days - 70 hold-out scenarios, all evaluated with the frozen calibration (fitted on dev only; nothing was refitted).

P10-P90 coverage on the evaluated scenarios (target 75-85%):

| | Intervals | Raw coverage | Calibrated coverage |
| --- | --- | --- | --- |
| All | 1120 | 75% | 74% |
| do_nothing | 280 | 79% | 72% |
| budget_-30% | 280 | 79% | 80% |
| budget_+20% | 280 | 79% | 82% |
| pause | 280 | 64% | 63% |

| Kind : metric | Intervals | Raw coverage | Factor | Calibrated coverage |
| --- | --- | --- | --- | --- |
| do_nothing:contribution_margin | 70 | 80% | -0.1272 | 67% |
| do_nothing:net_profit | 70 | 77% | -0.1376 | 67% |
| do_nothing:units | 70 | 90% | -0.2843 | 73% |
| do_nothing:ad_spend | 70 | 67% | 0.2676 | 80% |
| action:contribution_margin | 210 | 73% | 0.0579 | 75% |
| action:net_profit | 210 | 73% | 0.0784 | 76% |
| action:units | 210 | 85% | -0.1886 | 72% |
| action:ad_spend | 210 | 64% | 0.3844 | 78% |

An interval [P10, P90] of half-width w becomes [P10 - q w, P90 + q w]. Price changes are
not calibrated: the generator's demand does not respond to price, so price answers rest
on the documented elasticity prior and carry `low_evidence`.
