# Benchmark report: `dev` suite

Run 2026-10-27T22:49:41+00:00 - thresholds v1 - 84 scenarios - total runtime 245.1 s (mean 21.63 s, max 35.689 s per scenario).

## Overall (faulty scenarios)

| Top-1 | Top-3 | Detection | Mean delay (days) | Attribution: largest negative | Attribution: significant | Tracking breaks as data quality | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 89% | 89% | 89% | 7.39 | 61% | 52% | 100% | 0 |

## Alerting

| False profit alerts (healthy) | Alert precision | Profit alerts per healthy store-month | Alerts | Materiality-gated incidents per scenario | Incidents by level |
| --- | --- | --- | --- | --- | --- |
| 1 / 20 | 88% | 0.0125 | 32 | 0.8 | critical 23, data_quality 9, watchlist 67 |

## Per fault type

| Fault type | n | Top-1 | Top-3 | Detection | Median delay | Attribution check | Other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cannibalization | 8 | 88% | 88% | 88% | 12 | 38% |  |
| cpa_drift | 8 | 62% | 62% | 75% | 12.0 | 38% |  |
| fee_increase | 8 | 100% | 100% | 100% | 1.0 | 38% |  |
| healthy | 20 | - | - | - | - | - | false profit alerts 1 / 20 |
| mix_shift | 8 | 88% | 88% | 75% | 4.5 | 88% |  |
| refund_spike | 8 | 75% | 75% | 75% | 20.5 | 75% |  |
| stockout_on_promoted | 8 | 100% | 100% | 100% | 3.0 | 100% |  |
| supplier_cost_increase | 8 | 100% | 100% | 100% | 2.0 | 50% |  |
| tracking_break | 8 | 100% | 100% | 100% | 2.0 | n/a | classified as data quality 100% |

## Scenarios that failed

- `dev-cannibalization-01` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): attribution driver. Primary: cannibalization campaign:179d5e19-460a-5491-af07-4d0469ef8d60; largest negative driver: volume (expected ad_spend).
- `dev-cannibalization-02` (cannibalization magnitude 0.80 from day 70 (2026-08-10)): attribution driver. Primary: cannibalization campaign:03814fb3-6305-5054-ae83-f447b053ed6a; largest negative driver: volume (expected ad_spend).
- `dev-cannibalization-04` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: volume (expected ad_spend).
- `dev-cannibalization-06` (cannibalization magnitude 0.80 from day 70 (2026-08-10)): attribution driver. Primary: cannibalization campaign:acbabd40-34ef-5e9c-8d3b-3da07d8494ff; largest negative driver: refunds (expected ad_spend).
- `dev-cannibalization-08` (cannibalization magnitude 1.50 from day 84 (2026-08-24)): attribution driver. Primary: cannibalization campaign:87253382-736e-54a3-ac61-d911bc3eb48b; largest negative driver: volume (expected ad_spend).
- `dev-cpa_drift-01` (cpa_drift (subtle) magnitude 0.20 from day 84 (2026-08-24)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: refunds (expected volume).
- `dev-cpa_drift-02` (cpa_drift magnitude 0.50 from day 70 (2026-08-10)): wrong top-1, not top-3, attribution driver. Primary: tracking_break campaign:2806491a-3520-5880-979e-69acefe22307; largest negative driver: refunds (expected volume).
- `dev-cpa_drift-04` (cpa_drift (subtle) magnitude 0.20 from day 84 (2026-08-24)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: volume (expected volume).
- `dev-cpa_drift-05` (cpa_drift magnitude 0.35 from day 56 (2026-07-27)): attribution driver. Primary: cpa_drift campaign:0b93532f-379d-513b-b269-413ed5495d79; largest negative driver: mix (expected volume).
- `dev-cpa_drift-06` (cpa_drift magnitude 0.50 from day 70 (2026-08-10)): attribution driver. Primary: cpa_drift campaign:27832651-7068-5724-8dcb-9038bde51bd3; largest negative driver: fixed_costs (expected volume).
- `dev-cpa_drift-07` (cpa_drift magnitude 0.65 from day 63 (2026-08-03)): attribution driver. Primary: cpa_drift campaign:95888aef-a1fe-55f6-90c7-aff0892827a8; largest negative driver: mix (expected volume).
- `dev-fee_increase-02` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): attribution driver. Primary: fee_increase product:fe224179-6869-5bad-bf04-11e658f9c55f; largest negative driver: refunds (expected fees).
- `dev-fee_increase-03` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): attribution driver. Primary: fee_increase product:3b155ebd-127a-5b98-882c-8b8a0cf68495; largest negative driver: refunds (expected fees).
- `dev-fee_increase-04` (fee_increase (subtle) magnitude 0.15 from day 79 (2026-08-19)): attribution driver. Primary: fee_increase store; largest negative driver: volume (expected fees).
- `dev-fee_increase-06` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): attribution driver. Primary: fee_increase product:077c15c6-7328-5a1f-b910-1a8b12adaf3f; largest negative driver: refunds (expected fees).
- `dev-fee_increase-08` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): attribution driver. Primary: fee_increase product:2c04d9a7-2fdb-520f-8221-8b06413033f1; largest negative driver: refunds (expected fees).
- `dev-healthy-08` (healthy store, no fault): false alert. Primary: refund_spike product:52c93995-619f-5013-b7ce-64569c53fd51; largest negative driver: volume.
- `dev-mix_shift-04` (mix_shift (subtle) magnitude 0.15 from day 82 (2026-08-22)): not detected. Primary: mix_shift store; largest negative driver: mix (expected mix).
- `dev-mix_shift-05` (mix_shift magnitude 0.25 from day 59 (2026-07-30)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: refunds (expected mix).
- `dev-refund_spike-01` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: mix (expected refunds).
- `dev-refund_spike-04` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: refunds (expected refunds).
- `dev-refund_spike-05` (refund_spike magnitude 0.10 from day 60 (2026-07-31)): attribution driver. Primary: refund_spike product:ad0b6925-0c50-5390-bae9-47e23dc58116; largest negative driver: mix (expected refunds).
- `dev-supplier_cost_increase-01` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): attribution driver. Primary: supplier_cost_increase product:0f0eefd0-256d-5a8f-80e9-cbd064e654a3; largest negative driver: mix (expected unit_cost).
- `dev-supplier_cost_increase-02` (supplier_cost_increase magnitude 0.20 from day 67 (2026-08-07)): attribution driver. Primary: supplier_cost_increase product:e30c7706-8e2c-591e-86da-084ecb390d0d; largest negative driver: ad_spend (expected unit_cost).
- `dev-supplier_cost_increase-04` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): attribution driver. Primary: supplier_cost_increase product:0ac43d29-fed1-57f9-945c-26b65530ff04; largest negative driver: volume (expected unit_cost).
- `dev-supplier_cost_increase-05` (supplier_cost_increase magnitude 0.10 from day 58 (2026-07-29)): attribution driver. Primary: supplier_cost_increase product:715f5814-8038-5158-80b2-9d795285cc6f; largest negative driver: refunds (expected unit_cost).
