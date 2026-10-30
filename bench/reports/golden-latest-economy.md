# Golden questions

Run 2026-10-30T09:44:24+00:00 - routing economy - mode live.

| Active questions | Passed | Pass rate | Cost USD | Cost at Standard prices USD |
| --- | --- | --- | --- | --- |
| 30 | 24 | 80% | 0.058586404 | 1.02463255 |

| Type | Questions | Passed |
| --- | --- | --- |
| data_question | 2 | 2 |
| diagnose | 10 | 7 |
| evaluate | 4 | 4 |
| explain | 2 | 1 |
| improve | 4 | 3 |
| lookup | 3 | 2 |
| out_of_scope | 1 | 1 |
| review | 2 | 2 |
| what_if | 2 | 2 |

Investigations run for diagnoses (their cost is not in the answers' cost above):

| Investigations | Escalated | Models | Cost USD | Mean cost USD | Max cost USD | Mean at Standard prices USD | Mean latency (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17 | 3 | muse-spark-1.3-contributor 17 | 0.066315854 | 0.003901 | 0.005111026 | 0.070523 | 97.2 |

## Pending


## Failed

- `q02` (lookup): reference:attributed_contribution (cited ['ad_spend', 'attributed_revenue'])
- `q04` (explain): reference:attributed_contribution (cited ['campaign_profit']); reference:ad_spend (cited ['campaign_profit'])
- `q06` (diagnose): reference:campaign_profit (cited ['expected_monthly_impact', 'fees', 'gross_margin', 'profit_delta', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.volume', 'refunds', 'revenue']); reference:cpa (cited ['expected_monthly_impact', 'fees', 'gross_margin', 'profit_delta', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.volume', 'refunds', 'revenue']); root_cause (top cause mix_shift)
- `q07` (diagnose): reference:gross_margin (cited ['cogs', 'expected_monthly_impact', 'profit_delta', 'profit_driver.mix', 'profit_driver.unit_cost', 'revenue', 'units'])
- `q09` (diagnose): reference:contribution_margin (cited ['expected_monthly_impact', 'gross_margin', 'profit_delta', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.price', 'profit_driver.refunds', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue', 'units'])
- `q15` (improve): action_family (got increase_budget_capped)
