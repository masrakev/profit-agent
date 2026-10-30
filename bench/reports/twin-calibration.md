# Twin calibration (`dev`)

Run 2026-10-30T02:36:03+00:00 - calibration v2 (split_conformal_v1) - horizon 14 days - 154 scenarios, 77 held out for evaluation (odd index), the others calibrate.

P10-P90 coverage on the evaluated scenarios (target 75-85%):

| | Intervals | Raw coverage | Calibrated coverage |
| --- | --- | --- | --- |
| All | 1232 | 77% | 78% |
| do_nothing | 308 | 81% | 78% |
| budget_-30% | 308 | 78% | 80% |
| budget_+20% | 308 | 84% | 86% |
| pause | 308 | 67% | 70% |

| Kind : metric | Intervals | Raw coverage | Factor | Calibrated coverage |
| --- | --- | --- | --- | --- |
| do_nothing:contribution_margin | 77 | 83% | -0.1272 | 78% |
| do_nothing:net_profit | 77 | 82% | -0.1376 | 78% |
| do_nothing:units | 77 | 88% | -0.2843 | 77% |
| do_nothing:ad_spend | 77 | 69% | 0.2676 | 79% |
| action:contribution_margin | 231 | 78% | 0.0579 | 79% |
| action:net_profit | 231 | 78% | 0.0784 | 79% |
| action:units | 231 | 87% | -0.1886 | 80% |
| action:ad_spend | 231 | 63% | 0.3844 | 77% |

An interval [P10, P90] of half-width w becomes [P10 - q w, P90 + q w]. Price changes are
not calibrated: the generator's demand does not respond to price, so price answers rest
on the documented elasticity prior and carry `low_evidence`.
