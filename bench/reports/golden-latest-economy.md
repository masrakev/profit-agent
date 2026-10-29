# Golden questions

Run 2026-10-29T15:07:27+00:00 - routing economy - mode live.

| Active questions | Passed | Pass rate | Cost USD | Cost at Standard prices USD |
| --- | --- | --- | --- | --- |
| 22 | 15 | 68% | 0.030617056 | 0.53891245 |

| Type | Questions | Passed |
| --- | --- | --- |
| data_question | 2 | 2 |
| diagnose | 10 | 6 |
| explain | 2 | 1 |
| improve | 4 | 2 |
| lookup | 3 | 3 |
| out_of_scope | 1 | 1 |

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

- `q04` (explain): reference:attributed_contribution (cited ['campaign_profit']); reference:ad_spend (cited ['campaign_profit'])
- `q06` (diagnose): reference:campaign_profit (cited ['expected_monthly_impact', 'gross_margin', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.unit_cost', 'revenue', 'units']); reference:cpa (cited ['expected_monthly_impact', 'gross_margin', 'profit_driver.mix', 'profit_driver.refunds', 'profit_driver.unit_cost', 'revenue', 'units']); mention:label.campaign (expected campaign:735fb858-1ef6-5406-9480-cd5e5700b234); root_cause (top cause mix_shift)
- `q08` (diagnose): reference:refunds (cited ['expected_monthly_impact', 'profit_delta', 'profit_driver.refunds', 'refund_rate'])
- `q09` (diagnose): reference:contribution_margin (cited ['expected_monthly_impact', 'gross_margin', 'profit_delta', 'profit_driver.mix', 'profit_driver.price', 'profit_driver.unit_cost', 'profit_driver.volume', 'revenue'])
- `q11` (diagnose): reference:inventory_cover_days (cited ['ad_spend', 'attributed_purchases', 'attributed_revenue', 'campaign_profit', 'clicks', 'cpa', 'expected_monthly_impact', 'promoted_revenue', 'units', 'units_on_hand'])
- `q15` (improve): action_family (got fix_tracking)
- `q18` (improve): opportunity_without_range (a recommendation without an impact range)
