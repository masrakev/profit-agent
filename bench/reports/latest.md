# Benchmark report: `test_v2` suite

Run 2026-10-27T23:05:13+00:00 - thresholds v1 - 70 scenarios - total runtime 278.9 s (mean 29.07 s, max 44.201 s per scenario).

## Overall (faulty scenarios)

| Top-1 | Top-3 | Detection | Mean delay (days) | Attribution: largest negative | Attribution: significant | Tracking breaks as data quality | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 80% | 85% | 88% | 6.23 | 54% | 49% | 100% | 0 |

## Alerting

| False profit alerts (healthy) | Alert precision | Profit alerts per healthy store-month | Alerts | Materiality-gated incidents per scenario | Incidents by level |
| --- | --- | --- | --- | --- | --- |
| 1 / 30 | 89% | 0.0083 | 19 | 0.83 | critical 14, data_quality 5, watchlist 58 |

## Per fault type

| Fault type | n | Top-1 | Top-3 | Detection | Median delay | Attribution check | Other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cannibalization | 5 | 40% | 60% | 80% | 12.0 | 60% |  |
| cpa_drift | 5 | 100% | 100% | 100% | 11 | 80% |  |
| fee_increase | 5 | 80% | 80% | 100% | 0 | 40% |  |
| healthy | 30 | - | - | - | - | - | false profit alerts 1 / 30 |
| mix_shift | 5 | 80% | 80% | 80% | 3.5 | 60% |  |
| refund_spike | 5 | 40% | 60% | 40% | 17.5 | 80% |  |
| stockout_on_promoted | 5 | 100% | 100% | 100% | 3 | 60% |  |
| supplier_cost_increase | 5 | 100% | 100% | 100% | 2 | 0% |  |
| tracking_break | 5 | 100% | 100% | 100% | 2 | n/a | classified as data quality 100% |

## Scenarios that failed

- `test_v2-cannibalization-01` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: ad_spend (expected ad_spend).
- `test_v2-cannibalization-02` (cannibalization magnitude 0.50 from day 63 (2026-08-03)): attribution driver. Primary: cannibalization campaign:98af0504-4bd9-5889-8b07-e15a34654ac6; largest negative driver: mix (expected ad_spend).
- `test_v2-cannibalization-03` (cannibalization magnitude 0.80 from day 70 (2026-08-10)): wrong top-1, not top-3, attribution driver. Primary: mix_shift store; largest negative driver: refunds (expected ad_spend).
- `test_v2-cannibalization-05` (cannibalization magnitude 1.50 from day 84 (2026-08-24)): wrong top-1. Primary: cpa_drift campaign:74abae05-1904-5266-98a5-6119b51351e5; largest negative driver: ad_spend (expected ad_spend).
- `test_v2-cpa_drift-02` (cpa_drift magnitude 0.35 from day 56 (2026-07-27)): attribution driver. Primary: cpa_drift campaign:772ebf21-3d81-582b-ac8e-d4846cb3d9b3; largest negative driver: refunds (expected volume).
- `test_v2-fee_increase-02` (fee_increase magnitude 0.30 from day 61 (2026-08-01)): attribution driver. Primary: fee_increase store; largest negative driver: refunds (expected fees).
- `test_v2-fee_increase-03` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): wrong top-1, not top-3, attribution driver. Primary: stockout_on_promoted product:7c8133e1-ba3e-56a4-aa45-15c5daaff0df; largest negative driver: volume (expected fees).
- `test_v2-fee_increase-05` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): attribution driver. Primary: fee_increase product:a233cc8e-9f89-5421-b788-6c946cc0f130; largest negative driver: mix (expected fees).
- `test_v2-healthy-08` (healthy store, no fault): false alert. Primary: mix_shift store; largest negative driver: mix.
- `test_v2-mix_shift-01` (mix_shift (subtle) magnitude 0.15 from day 82 (2026-08-22)): wrong top-1, not top-3, attribution driver. Primary: refund_spike product:7e545adc-a9d6-555b-b3cc-8be980e45f31; largest negative driver: refunds (expected mix).
- `test_v2-mix_shift-03` (mix_shift magnitude 0.35 from day 66 (2026-08-06)): not detected, attribution driver. Primary: mix_shift store; largest negative driver: refunds (expected mix).
- `test_v2-refund_spike-01` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3, attribution driver. Primary: mix_shift store; largest negative driver: volume (expected refunds).
- `test_v2-refund_spike-02` (refund_spike magnitude 0.10 from day 60 (2026-07-31)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: refunds (expected refunds).
- `test_v2-refund_spike-03` (refund_spike magnitude 0.15 from day 68 (2026-08-08)): not detected, wrong top-1. Primary: mix_shift store; largest negative driver: refunds (expected refunds).
- `test_v2-stockout_on_promoted-01` (stockout_on_promoted (subtle) magnitude 1 from day 88 (2026-08-28)): attribution driver. Primary: stockout_on_promoted product:3aac1a15-8edf-5d8c-93a9-e7e3fd82a6aa; largest negative driver: mix (expected volume).
- `test_v2-stockout_on_promoted-05` (stockout_on_promoted magnitude 1 from day 78 (2026-08-18)): attribution driver. Primary: stockout_on_promoted product:0c220d11-0d0e-5fae-8049-40c72a116812; largest negative driver: mix (expected volume).
- `test_v2-supplier_cost_increase-01` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): attribution driver. Primary: supplier_cost_increase product:09e6cf49-93d9-5600-a988-4b97499eb5b9; largest negative driver: refunds (expected unit_cost).
- `test_v2-supplier_cost_increase-02` (supplier_cost_increase magnitude 0.10 from day 58 (2026-07-29)): attribution driver. Primary: supplier_cost_increase product:234d9679-b0f5-5926-8827-d848996425e7; largest negative driver: ad_spend (expected unit_cost).
- `test_v2-supplier_cost_increase-03` (supplier_cost_increase magnitude 0.20 from day 67 (2026-08-07)): attribution driver. Primary: supplier_cost_increase product:3ad5b291-2829-50e7-896c-7b1de2c47578; largest negative driver: volume (expected unit_cost).
- `test_v2-supplier_cost_increase-04` (supplier_cost_increase magnitude 0.30 from day 74 (2026-08-14)): attribution driver. Primary: supplier_cost_increase product:917b752e-204d-5529-8ef0-90954db98319; largest negative driver: refunds (expected unit_cost).
- `test_v2-supplier_cost_increase-05` (supplier_cost_increase magnitude 0.50 from day 62 (2026-08-02)): attribution driver. Primary: supplier_cost_increase product:ce27ed9c-099b-5491-b8ac-53fec920e698; largest negative driver: volume (expected unit_cost).
