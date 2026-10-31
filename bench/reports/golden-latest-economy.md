# Golden questions

Run 2026-10-31T13:44:59+00:00 - routing economy - mode live.

| Active questions | Passed | Pass rate | Cost USD | Cost at Standard prices USD |
| --- | --- | --- | --- | --- |
| 36 | 30 | 83% | 0.056688036 | 1.02366495 |

| Type | Questions | Passed |
| --- | --- | --- |
| data_question | 2 | 2 |
| diagnose | 10 | 7 |
| evaluate | 4 | 4 |
| explain | 2 | 1 |
| goal | 6 | 6 |
| improve | 4 | 3 |
| lookup | 3 | 2 |
| out_of_scope | 1 | 1 |
| review | 2 | 2 |
| what_if | 2 | 2 |

Investigations run for diagnoses (their cost is not in the answers' cost above):

| Investigations | Escalated | Models | Cost USD | Mean cost USD | Max cost USD | Mean at Standard prices USD | Mean latency (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17 | 3 | muse-spark-1.3-contributor 17 | 0.072921464 | 0.004289 | 0.007428268 | 0.076546 | 86.6 |

## Pending


## Failed

- `q02` (lookup): reference:ad_spend (cited ['expected_monthly_impact']); reference:attributed_revenue (cited ['expected_monthly_impact']); reference:attributed_contribution (cited ['expected_monthly_impact'])
- `q04` (explain): reference:campaign_profit (cited ['ad_spend', 'attributed_purchases', 'attributed_revenue', 'attribution_ratio', 'promoted_revenue', 'roas']); reference:attributed_contribution (cited ['ad_spend', 'attributed_purchases', 'attributed_revenue', 'attribution_ratio', 'promoted_revenue', 'roas'])
- `q06` (diagnose): reference:campaign_profit (cited ['expected_monthly_impact', 'gross_margin', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.refunds', 'revenue']); reference:cpa (cited ['expected_monthly_impact', 'gross_margin', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.refunds', 'revenue']); mention:label.campaign (expected campaign:735fb858-1ef6-5406-9480-cd5e5700b234); root_cause (top cause mix_shift)
- `q07` (diagnose): reference:gross_margin (cited ['cogs', 'expected_monthly_impact', 'profit_delta', 'profit_driver.mix', 'profit_driver.unit_cost', 'revenue', 'units'])
- `q09` (diagnose): reference:contribution_margin (cited ['expected_monthly_impact', 'gross_margin', 'profit_delta', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue'])
- `q15` (improve): action_family (got increase_budget_capped)
