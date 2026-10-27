# Benchmark report: `test` suite

Run 2026-10-27T18:00:31+00:00 - thresholds v1 - 50 scenarios - total runtime 124.8 s (mean 9.58 s, max 14.998 s per scenario).

## Overall (faulty scenarios)

| Top-1 | Top-3 | Detection | Mean delay (days) | Attribution check | False alerts (healthy) | Tracking breaks as data quality | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 80% | 85% | 85% | 7.38 | 66% | 30% | 100% | 0 |

## Per fault type

| Fault type | n | Top-1 | Top-3 | Detection | Median delay | Attribution check | Other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cannibalization | 5 | 80% | 80% | 80% | 12.5 | 40% |  |
| cpa_drift | 5 | 40% | 40% | 60% | 12 | 40% |  |
| fee_increase | 5 | 100% | 100% | 100% | 0 | 40% |  |
| healthy | 10 | - | - | - | - | - | false alerts 30% |
| mix_shift | 5 | 40% | 80% | 60% | 4 | 80% |  |
| refund_spike | 5 | 80% | 80% | 80% | 24.5 | 100% |  |
| stockout_on_promoted | 5 | 100% | 100% | 100% | 3 | 100% |  |
| supplier_cost_increase | 5 | 100% | 100% | 100% | 2 | 60% |  |
| tracking_break | 5 | 100% | 100% | 100% | 2 | n/a | classified as data quality 100% |

## Scenarios that failed

- `test-cannibalization-01` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: volume (expected ad_spend).
- `test-cannibalization-03` (cannibalization magnitude 0.80 from day 70 (2026-08-10)): attribution driver. Primary: cannibalization campaign:acbabd40-34ef-5e9c-8d3b-3da07d8494ff; largest negative driver: refunds (expected ad_spend).
- `test-cannibalization-05` (cannibalization magnitude 1.50 from day 84 (2026-08-24)): attribution driver. Primary: cannibalization campaign:87253382-736e-54a3-ac61-d911bc3eb48b; largest negative driver: volume (expected ad_spend).
- `test-cpa_drift-01` (cpa_drift (subtle) magnitude 0.20 from day 84 (2026-08-24)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: volume (expected volume).
- `test-cpa_drift-02` (cpa_drift magnitude 0.35 from day 56 (2026-07-27)): not detected, wrong top-1, not top-3, attribution driver. Primary: mix_shift store; largest negative driver: fixed_costs (expected volume).
- `test-cpa_drift-03` (cpa_drift magnitude 0.50 from day 70 (2026-08-10)): attribution driver. Primary: cpa_drift campaign:27832651-7068-5724-8dcb-9038bde51bd3; largest negative driver: fixed_costs (expected volume).
- `test-cpa_drift-04` (cpa_drift magnitude 0.65 from day 63 (2026-08-03)): wrong top-1, not top-3, attribution driver. Primary: tracking_break campaign:95888aef-a1fe-55f6-90c7-aff0892827a8; largest negative driver: refunds (expected volume).
- `test-fee_increase-01` (fee_increase (subtle) magnitude 0.15 from day 79 (2026-08-19)): attribution driver. Primary: fee_increase store; largest negative driver: volume (expected fees).
- `test-fee_increase-03` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): attribution driver. Primary: fee_increase product:077c15c6-7328-5a1f-b910-1a8b12adaf3f; largest negative driver: refunds (expected fees).
- `test-fee_increase-05` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): attribution driver. Primary: fee_increase product:2c04d9a7-2fdb-520f-8221-8b06413033f1; largest negative driver: refunds (expected fees).
- `test-healthy-02` (healthy store, no fault): false alert. Primary: refund_spike product:52c93995-619f-5013-b7ce-64569c53fd51; largest negative driver: refunds.
- `test-healthy-03` (healthy store, no fault): false alert. Primary: mix_shift store; largest negative driver: mix.
- `test-healthy-10` (healthy store, no fault): false alert. Primary: refund_spike product:0b054fce-15b7-54d9-9b56-ea0a7502bd1a; largest negative driver: refunds.
- `test-mix_shift-01` (mix_shift (subtle) magnitude 0.15 from day 82 (2026-08-22)): not detected. Primary: mix_shift store; largest negative driver: mix (expected mix).
- `test-mix_shift-02` (mix_shift magnitude 0.25 from day 59 (2026-07-30)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: refunds (expected mix).
- `test-mix_shift-03` (mix_shift magnitude 0.35 from day 66 (2026-08-06)): wrong top-1. Primary: stockout_on_promoted product:6c24b005-f5d4-54fe-a1db-2dbef5d35358; largest negative driver: mix (expected mix).
- `test-mix_shift-04` (mix_shift magnitude 0.50 from day 73 (2026-08-13)): wrong top-1. Primary: stockout_on_promoted product:11490bf1-c1a1-57fc-b2fa-5e000166bf9f; largest negative driver: mix (expected mix).
- `test-refund_spike-01` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: refunds (expected refunds).
- `test-supplier_cost_increase-01` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): attribution driver. Primary: supplier_cost_increase product:0ac43d29-fed1-57f9-945c-26b65530ff04; largest negative driver: volume (expected unit_cost).
- `test-supplier_cost_increase-02` (supplier_cost_increase magnitude 0.10 from day 58 (2026-07-29)): attribution driver. Primary: supplier_cost_increase product:715f5814-8038-5158-80b2-9d795285cc6f; largest negative driver: refunds (expected unit_cost).
