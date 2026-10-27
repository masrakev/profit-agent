# Benchmark report: `dev` suite

Run 2026-10-27T18:04:25+00:00 - thresholds v1 - 30 scenarios - total runtime 69.1 s (mean 8.41 s, max 11.834 s per scenario).

## Overall (faulty scenarios)

| Top-1 | Top-3 | Detection | Mean delay (days) | Attribution check | False alerts (healthy) | Tracking breaks as data quality | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 88% | 88% | 92% | 6.55 | 57% | 17% | 67% | 0 |

## Per fault type

| Fault type | n | Top-1 | Top-3 | Detection | Median delay | Attribution check | Other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cannibalization | 3 | 100% | 100% | 100% | 12 | 33% |  |
| cpa_drift | 3 | 67% | 67% | 67% | 11.0 | 67% |  |
| fee_increase | 3 | 100% | 100% | 100% | 2 | 33% |  |
| healthy | 6 | - | - | - | - | - | false alerts 17% |
| mix_shift | 3 | 100% | 100% | 100% | 7 | 100% |  |
| refund_spike | 3 | 67% | 67% | 67% | 19.0 | 33% |  |
| stockout_on_promoted | 3 | 100% | 100% | 100% | 3 | 100% |  |
| supplier_cost_increase | 3 | 100% | 100% | 100% | 2 | 33% |  |
| tracking_break | 3 | 67% | 67% | 100% | 2 | n/a | classified as data quality 67% |

## Scenarios that failed

- `dev-cannibalization-01` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): attribution driver. Primary: cannibalization campaign:179d5e19-460a-5491-af07-4d0469ef8d60; largest negative driver: volume (expected ad_spend).
- `dev-cannibalization-02` (cannibalization magnitude 0.80 from day 70 (2026-08-10)): attribution driver. Primary: cannibalization campaign:03814fb3-6305-5054-ae83-f447b053ed6a; largest negative driver: volume (expected ad_spend).
- `dev-cpa_drift-01` (cpa_drift (subtle) magnitude 0.20 from day 84 (2026-08-24)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: refunds (expected volume).
- `dev-fee_increase-02` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): attribution driver. Primary: fee_increase product:fe224179-6869-5bad-bf04-11e658f9c55f; largest negative driver: refunds (expected fees).
- `dev-fee_increase-03` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): attribution driver. Primary: fee_increase product:3b155ebd-127a-5b98-882c-8b8a0cf68495; largest negative driver: refunds (expected fees).
- `dev-healthy-05` (healthy store, no fault): false alert. Primary: cpa_drift campaign:68b62bc6-161b-5e10-99ab-5467ff642bc2; largest negative driver: refunds.
- `dev-refund_spike-01` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: mix (expected refunds).
- `dev-refund_spike-02` (refund_spike magnitude 0.15 from day 68 (2026-08-08)): attribution driver. Primary: refund_spike product:44601ce6-e1e5-509d-ad2b-329c98d405cc; largest negative driver: mix (expected refunds).
- `dev-supplier_cost_increase-01` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): attribution driver. Primary: supplier_cost_increase product:0f0eefd0-256d-5a8f-80e9-cbd064e654a3; largest negative driver: mix (expected unit_cost).
- `dev-supplier_cost_increase-02` (supplier_cost_increase magnitude 0.20 from day 67 (2026-08-07)): attribution driver. Primary: supplier_cost_increase product:e30c7706-8e2c-591e-86da-084ecb390d0d; largest negative driver: ad_spend (expected unit_cost).
- `dev-tracking_break-01` (tracking_break (subtle) magnitude 0.60 from day 81 (2026-08-21)): wrong top-1, not top-3, tracking break not data quality. Primary: cpa_drift campaign:9ac81ef3-7a91-5ddd-924e-b552f06bf670; largest negative driver: fixed_costs.
