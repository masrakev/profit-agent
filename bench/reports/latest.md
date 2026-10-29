# Benchmark report: `test_v3` suite

Run 2026-10-29T17:51:59+00:00 - thresholds v1 - 70 scenarios - total runtime 141.4 s (mean 14.56 s, max 22.441 s per scenario).

## Overall (faulty scenarios)

| Top-1 | Top-3 | Detection | Mean delay (days) | Attribution: largest negative | Attribution: significant | Tracking breaks as data quality | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 70% | 75% | 80% | 5.62 | 51% | 54% | 80% | 0 |

## Alerting

| False profit alerts (healthy) | Alert precision | Profit alerts per healthy store-month | Alerts | Materiality-gated incidents per scenario | Incidents by level |
| --- | --- | --- | --- | --- | --- |
| 1 / 30 | 78% | 0.0083 | 23 | 0.79 | critical 9, data_quality 4, high 3, normal 7, watchlist 55 |

## Per fault type

| Fault type | n | Top-1 | Top-3 | Detection | Median delay | Attribution check | Other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cannibalization | 5 | 40% | 60% | 60% | 13 | 60% |  |
| cpa_drift | 5 | 80% | 80% | 80% | 12.0 | 40% |  |
| fee_increase | 5 | 60% | 60% | 100% | 2 | 40% |  |
| healthy | 30 | - | - | - | - | - | false profit alerts 1 / 30 |
| mix_shift | 5 | 80% | 80% | 60% | 12 | 100% |  |
| refund_spike | 5 | 40% | 40% | 40% | 16.0 | 20% |  |
| stockout_on_promoted | 5 | 100% | 100% | 100% | 3 | 80% |  |
| supplier_cost_increase | 5 | 80% | 100% | 100% | 2 | 20% |  |
| tracking_break | 5 | 80% | 80% | 100% | 2 | n/a | classified as data quality 80% |

## Scenarios that failed

- `test_v3-cannibalization-01` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: volume (expected ad_spend).
- `test_v3-cannibalization-02` (cannibalization magnitude 0.50 from day 63 (2026-08-03)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: volume (expected ad_spend).
- `test_v3-cannibalization-05` (cannibalization magnitude 1.50 from day 84 (2026-08-24)): wrong top-1. Primary: cpa_drift campaign:e9c438aa-6a9a-5670-9ecd-96b0ec518af6; largest negative driver: ad_spend (expected ad_spend).
- `test_v3-cpa_drift-01` (cpa_drift (subtle) magnitude 0.20 from day 84 (2026-08-24)): not detected, wrong top-1, not top-3. Primary: mix_shift store; largest negative driver: volume (expected volume).
- `test_v3-cpa_drift-02` (cpa_drift magnitude 0.35 from day 56 (2026-07-27)): attribution driver. Primary: cpa_drift campaign:796df973-3fe3-5ad3-8add-818db7b42d9c; largest negative driver: mix (expected volume).
- `test_v3-cpa_drift-03` (cpa_drift magnitude 0.50 from day 70 (2026-08-10)): attribution driver. Primary: cpa_drift campaign:6a1f0d86-6da4-599c-ac21-54dc70389c6d; largest negative driver: fixed_costs (expected volume).
- `test_v3-cpa_drift-04` (cpa_drift magnitude 0.65 from day 63 (2026-08-03)): attribution driver. Primary: cpa_drift campaign:42ec831f-44c1-50da-993c-b5ba018b5042; largest negative driver: refunds (expected volume).
- `test_v3-fee_increase-01` (fee_increase (subtle) magnitude 0.15 from day 79 (2026-08-19)): attribution driver. Primary: fee_increase store; largest negative driver: volume (expected fees).
- `test_v3-fee_increase-03` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): wrong top-1, not top-3, attribution driver. Primary: refund_spike product:586d1f1c-a11c-5384-8eee-d23d49ecad33; largest negative driver: volume (expected fees).
- `test_v3-fee_increase-05` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): wrong top-1, not top-3, attribution driver. Primary: mix_shift store; largest negative driver: ad_spend (expected fees).
- `test_v3-healthy-18` (healthy store, no fault): false alert. Primary: mix_shift store; largest negative driver: volume.
- `test_v3-mix_shift-01` (mix_shift (subtle) magnitude 0.15 from day 82 (2026-08-22)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: mix (expected mix).
- `test_v3-mix_shift-02` (mix_shift magnitude 0.25 from day 59 (2026-07-30)): not detected. Primary: mix_shift store; largest negative driver: mix (expected mix).
- `test_v3-refund_spike-01` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3, attribution driver. Primary: refund_spike product:0fc169cb-de9e-5282-aa76-c8a38347063d; largest negative driver: volume (expected refunds).
- `test_v3-refund_spike-02` (refund_spike magnitude 0.10 from day 60 (2026-07-31)): not detected, wrong top-1, not top-3, attribution driver. Primary: mix_shift store; largest negative driver: mix (expected refunds).
- `test_v3-refund_spike-03` (refund_spike magnitude 0.15 from day 68 (2026-08-08)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: fixed_costs (expected refunds).
- `test_v3-refund_spike-04` (refund_spike magnitude 0.25 from day 64 (2026-08-04)): attribution driver. Primary: refund_spike product:85fab1cc-a282-553e-afdd-ce4c25baf96a; largest negative driver: mix (expected refunds).
- `test_v3-stockout_on_promoted-04` (stockout_on_promoted magnitude 1 from day 66 (2026-08-06)): attribution driver. Primary: stockout_on_promoted product:a3da8e40-1894-5f26-a2eb-dbb385445969; largest negative driver: mix (expected volume).
- `test_v3-supplier_cost_increase-01` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): wrong top-1, attribution driver. Primary: mix_shift store; largest negative driver: mix (expected unit_cost).
- `test_v3-supplier_cost_increase-02` (supplier_cost_increase magnitude 0.10 from day 58 (2026-07-29)): attribution driver. Primary: supplier_cost_increase product:4f8db8af-0bfc-5788-bae4-597e23af0692; largest negative driver: refunds (expected unit_cost).
- `test_v3-supplier_cost_increase-03` (supplier_cost_increase magnitude 0.20 from day 67 (2026-08-07)): attribution driver. Primary: supplier_cost_increase product:b606bb24-d069-5a6f-b3da-92fc762d0fcb; largest negative driver: refunds (expected unit_cost).
- `test_v3-supplier_cost_increase-04` (supplier_cost_increase magnitude 0.30 from day 74 (2026-08-14)): attribution driver. Primary: supplier_cost_increase product:98021420-f13f-593c-964f-8ab9b880a7e7; largest negative driver: refunds (expected unit_cost).
- `test_v3-tracking_break-01` (tracking_break (subtle) magnitude 0.60 from day 81 (2026-08-21)): wrong top-1, not top-3, tracking break not data quality. Primary: refund_spike product:2ad73852-939a-5413-8bf0-4503b6a49f08; largest negative driver: volume.
