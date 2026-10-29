# Golden questions

Run 2026-10-29T17:36:55+00:00 - routing production - mode live.

| Active questions | Passed | Pass rate | Cost USD | Cost at Standard prices USD |
| --- | --- | --- | --- | --- |
| 22 | 17 | 77% | 0.487083132 | 0.53272640 |

| Type | Questions | Passed |
| --- | --- | --- |
| data_question | 2 | 2 |
| diagnose | 10 | 8 |
| explain | 2 | 2 |
| improve | 4 | 1 |
| lookup | 3 | 3 |
| out_of_scope | 1 | 1 |

Investigations run for diagnoses (their cost is not in the answers' cost above):

| Investigations | Escalated | Models | Cost USD | Mean cost USD | Max cost USD | Mean at Standard prices USD | Mean latency (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17 | 3 | muse-spark-1.3 14, muse-wonder-1.0 3 | 1.45310655 | 0.085477 | 0.1900240 | 0.085477 | 58.5 |

## Pending

- `q19`: evaluate questions need the simulation and decisions modules
- `q20`: evaluate questions need the simulation and decisions modules
- `q21`: evaluate questions need the simulation and decisions modules
- `q22`: evaluate questions need the simulation and decisions modules
- `q23`: what_if questions need the simulation and decisions modules
- `q24`: what_if questions need the simulation and decisions modules
- `q25`: needs a recorded budget decision on the drifting campaign and its outcome window
- `q26`: needs a recorded decision with too little post-decision history to measure (abstention)

## Failed

- `q06` (diagnose): reference:campaign_profit (cited ['derived.gap', 'derived.mean', 'derived.share', 'expected_monthly_impact', 'gross_margin', 'orders', 'profit_driver.ad_spend', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue']); reference:cpa (cited ['derived.gap', 'derived.mean', 'derived.share', 'expected_monthly_impact', 'gross_margin', 'orders', 'profit_driver.ad_spend', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue']); root_cause (top cause mix_shift)
- `q09` (diagnose): reference:contribution_margin (cited ['derived.gap', 'expected_monthly_impact', 'gross_margin', 'profit_delta', 'profit_driver.fees', 'profit_driver.mix', 'profit_driver.price', 'profit_driver.refunds', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue'])
- `q15` (improve): action_family (got fix_tracking)
- `q16` (improve): reference:campaign_profit (cited ['ad_spend', 'attributed_purchases', 'attributed_revenue', 'contribution_margin', 'cpa', 'inventory_cover_days', 'promoted_revenue', 'roas', 'units_on_hand']); reference:poas (cited ['ad_spend', 'attributed_purchases', 'attributed_revenue', 'contribution_margin', 'cpa', 'inventory_cover_days', 'promoted_revenue', 'roas', 'units_on_hand']); mention:label.campaign (expected campaign:ffd8653a-5c5c-5476-a930-8137da4841a3)
- `q18` (improve): opportunity_without_range (a recommendation without an impact range)
