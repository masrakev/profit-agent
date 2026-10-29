# Options on the golden scenarios

Run 2026-10-29T20:43:42+00:00. Twin fitted at each store's data end; ranges are the simulated change in net profit against doing nothing over 14 days (calibrated, store currency).

### `golden-cannibalization`: cannibalization on `campaign:e1c9f717-d839-5c47-b45b-52ba48ff9f13`

Floor over 14 days: 46.67. Recommended: `incrementality_test` (no simulated option beats doing nothing safely: manual step).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| reduce_budget -20% | reduce_or_reallocate_budget | -400 / -252 / -97 | reversible | spend outside the observed range: the response curve is extrapolated |
| reduce_budget -30% | reduce_or_reallocate_budget | -606 / -385 / -177 | reversible | spend outside the observed range: the response curve is extrapolated |
| pause_campaign | pause_or_reduce_campaign | -2,287 / -1,583 / -1,016 | reversible |  |
| incrementality_test (recommended) | monitor | not simulated | manual |  |

### `golden-cpa_drift`: cpa_drift on `campaign:735fb858-1ef6-5406-9480-cd5e5700b234`

Floor over 14 days: 46.67. Recommended: `reduce_budget` (best median gain among options whose downside stays within the floor).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| reduce_budget -20% (recommended) | reduce_or_reallocate_budget | -37 / 115 / 135 | reversible | spend outside the observed range: the response curve is extrapolated |
| reduce_budget -30% | reduce_or_reallocate_budget | -56 / 171 / 201 | reversible | spend outside the observed range: the response curve is extrapolated |
| pause_campaign | pause_or_reduce_campaign | -472 / -209 / -3 | reversible |  |

### `golden-fee_increase`: fee_increase on `store`

Floor over 14 days: 46.67. Recommended: `monitor` (no option beats doing nothing safely: monitor).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| monitor (recommended) | monitor | not simulated | none |  |

### `golden-mix_shift`: mix_shift on `store`

Floor over 14 days: 46.67. Recommended: `monitor` (no option beats doing nothing safely: monitor).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| monitor (recommended) | monitor | not simulated | none |  |

### `golden-refund_spike`: refund_spike on `product:eed9486b-43f0-5158-ba8f-b44f314c8293`

Floor over 14 days: 46.67. Recommended: `investigate_product_quality` (no simulated option beats doing nothing safely: manual step).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| investigate_product_quality (recommended) | investigate_product_quality | not simulated | manual |  |

### `golden-stockout_on_promoted`: stockout_on_promoted on `product:ea63836b-e0d7-5298-b9db-b58631ed27f1`

Floor over 14 days: 46.67. Recommended: `pause_until_restock` (best median gain among options whose downside stays within the floor).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| pause_until_restock for 14 days (recommended) | pause_or_reduce_campaign | 619 / 643 / 666 | reversible |  |
| reduce_budget -30% for 14 days | reduce_or_reallocate_budget | 186 / 193 / 200 | reversible | spend outside the observed range: the response curve is extrapolated |
| prepare_reorder | restock_product | not simulated | prepare_only |  |

### `golden-supplier_cost_increase`: supplier_cost_increase on `product:39e449c4-3e09-5f6a-8374-887f55192a79`

Floor over 14 days: 46.67. Recommended: `prepare_price_change` (best median gain among options whose downside stays within the floor).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| prepare_price_change +5% (recommended) | review_pricing | -7 / 16 / 42 | prepare_only | price response from the prior: the list price never changed enough |
| review_supplier | review_supplier_cost | not simulated | manual |  |

### `golden-tracking_break`: tracking_break on `campaign:e5aa2a04-68aa-5fb2-886b-3e85f0c3a38b`

Floor over 14 days: 46.67. Recommended: `fix_tracking` (no simulated option beats doing nothing safely: manual step).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| fix_tracking (recommended) | fix_tracking | not simulated | manual |  |

### `golden-underfunded_campaign`: underfunded_campaign on `campaign:ffd8653a-5c5c-5476-a930-8137da4841a3`

Floor over 14 days: 46.67. Recommended: `increase_budget` (best median gain among options whose downside stays within the floor).

| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |
| --- | --- | --- | --- | --- |
| increase_budget +10% (recommended) | increase_budget_capped | -29 / 235 / 426 | reversible |  |
| increase_budget +20% | increase_budget_capped | -69 / 451 / 851 | reversible | spend outside the observed range: the response curve is extrapolated |
