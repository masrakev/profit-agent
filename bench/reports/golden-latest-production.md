# Golden questions

Run 2026-10-30T09:23:09+00:00 - routing production - mode live.

| Active questions | Passed | Pass rate | Cost USD | Cost at Standard prices USD |
| --- | --- | --- | --- | --- |
| 30 | 22 | 73% | 0.899142424 | 0.96858595 |

| Type | Questions | Passed |
| --- | --- | --- |
| data_question | 2 | 2 |
| diagnose | 10 | 5 |
| evaluate | 4 | 4 |
| explain | 2 | 2 |
| improve | 4 | 3 |
| lookup | 3 | 2 |
| out_of_scope | 1 | 1 |
| review | 2 | 1 |
| what_if | 2 | 2 |

Investigations run for diagnoses (their cost is not in the answers' cost above):

| Investigations | Escalated | Models | Cost USD | Mean cost USD | Max cost USD | Mean at Standard prices USD | Mean latency (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17 | 3 | muse-spark-1.3 14, muse-wonder-1.0 3 | 1.46802890 | 0.086355 | 0.1978176 | 0.086355 | 62.1 |

## Pending


## Failed

- `q02` (lookup): reference:attributed_contribution (cited ['ad_spend', 'attributed_revenue'])
- `q06` (diagnose): reference:campaign_profit (cited ['derived.gap', 'derived.sum', 'expected_monthly_impact', 'profit_delta', 'profit_driver.ad_spend', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.volume', 'revenue']); reference:cpa (cited ['derived.gap', 'derived.sum', 'expected_monthly_impact', 'profit_delta', 'profit_driver.ad_spend', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.volume', 'revenue']); root_cause (top cause mix_shift)
- `q08` (diagnose): reference:refunds (cited ['expected_monthly_impact', 'profit_delta', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.volume', 'refund_rate'])
- `q09` (diagnose): reference:contribution_margin (cited ['attribution_ratio', 'derived.gap', 'expected_monthly_impact', 'gross_margin', 'profit_delta', 'profit_driver.mix', 'profit_driver.price', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue'])
- `q12` (diagnose): reference:attributed_revenue (cited ['attributed_purchases', 'attribution_ratio', 'campaign_profit', 'derived.share', 'expected_monthly_impact', 'orders', 'profit_delta', 'profit_driver.ad_spend', 'promoted_revenue'])
- `q13` (diagnose): reference:attribution_ratio (cited ['ad_spend', 'gross_margin', 'revenue']); flag:data_quality (flags ['abstain_insufficient_evidence'])
- `q15` (improve): action_family (got increase_budget_capped)
- `q25` (review): estimate_presented_as_exact (an estimate is called exact)
