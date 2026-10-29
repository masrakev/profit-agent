# Golden questions

Run 2026-10-29T20:53:31+00:00 - routing production - mode live.

| Active questions | Passed | Pass rate | Cost USD | Cost at Standard prices USD |
| --- | --- | --- | --- | --- |
| 28 | 23 | 82% | 0.672136468 | 0.73531885 |

| Type | Questions | Passed |
| --- | --- | --- |
| data_question | 2 | 2 |
| diagnose | 10 | 7 |
| evaluate | 4 | 4 |
| explain | 2 | 2 |
| improve | 4 | 3 |
| lookup | 3 | 2 |
| out_of_scope | 1 | 1 |
| what_if | 2 | 2 |

Investigations run for diagnoses (their cost is not in the answers' cost above):

| Investigations | Escalated | Models | Cost USD | Mean cost USD | Max cost USD | Mean at Standard prices USD | Mean latency (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17 | 3 | muse-spark-1.3 14, muse-wonder-1.0 3 | 1.69476540 | 0.099692 | 0.3286000 | 0.099692 | 60.0 |

## Pending

- `q25`: needs a recorded budget decision on the drifting campaign and its outcome window
- `q26`: needs a recorded decision with too little post-decision history to measure (abstention)

## Failed

- `q02` (lookup): reference:attributed_contribution (cited ['ad_spend', 'attributed_revenue', 'campaign_profit'])
- `q06` (diagnose): reference:campaign_profit (cited ['attribution_ratio', 'cpa', 'expected_monthly_impact', 'fees', 'gross_margin', 'profit_delta', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.volume', 'revenue']); root_cause (top cause mix_shift)
- `q07` (diagnose): reference:gross_margin (cited ['cogs', 'expected_monthly_impact', 'profit_delta', 'profit_driver.mix', 'profit_driver.unit_cost', 'units'])
- `q09` (diagnose): reference:contribution_margin (cited ['derived.gap', 'expected_monthly_impact', 'gross_margin', 'profit_delta', 'profit_driver.mix', 'profit_driver.price', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue'])
- `q15` (improve): action_family (got fix_tracking)
