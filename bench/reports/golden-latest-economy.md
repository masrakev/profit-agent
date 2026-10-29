# Golden questions

Run 2026-10-29T20:32:49+00:00 - routing economy - mode live.

| Active questions | Passed | Pass rate | Cost USD | Cost at Standard prices USD |
| --- | --- | --- | --- | --- |
| 28 | 24 | 86% | 0.044035318 | 0.77601260 |

| Type | Questions | Passed |
| --- | --- | --- |
| data_question | 2 | 2 |
| diagnose | 10 | 8 |
| evaluate | 4 | 4 |
| explain | 2 | 2 |
| improve | 4 | 3 |
| lookup | 3 | 2 |
| out_of_scope | 1 | 1 |
| what_if | 2 | 2 |

Investigations run for diagnoses (their cost is not in the answers' cost above):

| Investigations | Escalated | Models | Cost USD | Mean cost USD | Max cost USD | Mean at Standard prices USD | Mean latency (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17 | 3 | muse-spark-1.3-contributor 17 | 0.073086688 | 0.004299 | 0.007042312 | 0.074624 | 95.2 |

## Pending

- `q25`: needs a recorded budget decision on the drifting campaign and its outcome window
- `q26`: needs a recorded decision with too little post-decision history to measure (abstention)

## Failed

- `q02` (lookup): reference:attributed_contribution (cited ['ad_spend', 'attributed_revenue', 'roas'])
- `q06` (diagnose): reference:campaign_profit (cited ['attribution_ratio', 'expected_monthly_impact', 'gross_margin', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.price', 'profit_driver.refunds', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue']); reference:cpa (cited ['attribution_ratio', 'expected_monthly_impact', 'gross_margin', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.price', 'profit_driver.refunds', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue']); root_cause (top cause mix_shift)
- `q09` (diagnose): reference:contribution_margin (cited ['expected_monthly_impact', 'profit_delta', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.unit_cost', 'profit_driver.volume'])
- `q15` (improve): action_family (got increase_budget_capped)
