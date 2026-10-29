# Twin calibration (`dev`)

Run 2026-10-29T19:32:50+00:00 - calibration v1 (split_conformal_v1) - horizon 14 days - 154 scenarios, 77 held out for evaluation (odd index), the others calibrate.

P10-P90 coverage on the held-out scenarios (target 75-85%):

| | Intervals | Raw coverage | Calibrated coverage |
| --- | --- | --- | --- |
| All | 1232 | 74% | 79% |
| do_nothing | 308 | 76% | 79% |
| budget_-30% | 308 | 74% | 80% |
| budget_+20% | 308 | 79% | 81% |
| pause | 308 | 69% | 75% |

| Kind : metric | Intervals | Raw coverage | Factor | Calibrated coverage |
| --- | --- | --- | --- | --- |
| do_nothing:contribution_margin | 77 | 75% | 0.1434 | 79% |
| do_nothing:net_profit | 77 | 74% | 0.138 | 79% |
| do_nothing:units | 77 | 82% | -0.1846 | 78% |
| do_nothing:ad_spend | 77 | 71% | 0.2612 | 81% |
| action:contribution_margin | 231 | 74% | 0.1456 | 79% |
| action:net_profit | 231 | 74% | 0.1392 | 77% |
| action:units | 231 | 84% | -0.0166 | 82% |
| action:ad_spend | 231 | 63% | 0.3713 | 76% |

An interval [P10, P90] of half-width w becomes [P10 - q w, P90 + q w]. Price changes are
not calibrated: the generator's demand does not respond to price, so price answers rest
on the documented elasticity prior and carry `low_evidence`.
