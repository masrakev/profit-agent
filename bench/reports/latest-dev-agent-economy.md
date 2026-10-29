# Benchmark report: `dev-agent-economy` suite

Run 2026-10-29T16:03:58+00:00 - thresholds v1 - 154 scenarios - total runtime 2164.9 s (mean 82.51 s, max 180.458 s per scenario).

## Overall (faulty scenarios)

| Top-1 | Top-3 | Detection | Mean delay (days) | Attribution: largest negative | Attribution: significant | Tracking breaks as data quality | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 86% | 88% | 88% | 6.95 | 58% | 51% | 100% | 0 |

## Alerting

| False profit alerts (healthy) | Alert precision | Profit alerts per healthy store-month | Alerts | Materiality-gated incidents per scenario | Incidents by level |
| --- | --- | --- | --- | --- | --- |
| 2 / 50 | 88% | 0.01 | 51 | 0.81 | critical 21, data_quality 14, high 8, normal 8, watchlist 125 |

## Per fault type

| Fault type | n | Top-1 | Top-3 | Detection | Median delay | Attribution check | Other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cannibalization | 13 | 69% | 77% | 85% | 12 | 46% |  |
| cpa_drift | 13 | 77% | 77% | 85% | 12 | 54% |  |
| fee_increase | 13 | 92% | 92% | 100% | 0 | 38% |  |
| healthy | 50 | - | - | - | - | - | false profit alerts 2 / 50 |
| mix_shift | 13 | 85% | 85% | 77% | 4.0 | 77% |  |
| refund_spike | 13 | 62% | 69% | 62% | 20.5 | 77% |  |
| stockout_on_promoted | 13 | 100% | 100% | 100% | 3 | 85% |  |
| supplier_cost_increase | 13 | 100% | 100% | 100% | 2 | 31% |  |
| tracking_break | 13 | 100% | 100% | 100% | 2 | n/a | classified as data quality 100% |

## Agent (investigation of each primary incident)

| | Top-1 | Top-3 | Tracking breaks as data quality | False profit alerts | Level-2 attribution in scope |
| --- | --- | --- | --- | --- | --- |
| Deterministic baseline | 86% | 88% | 100% | 2 / 50 | 30% |
| Deterministic + agent | 86% | 88% | 100% | 2 / 50 (the agent changes no alert) | n/a |

Both rows count every faulty scenario; where nothing was investigated (no incident, or the investigation failed: 8 scenarios) the agent row keeps the pipeline's ranking. On the 96 investigated faulty scenarios alone, top-1 is 93% for the baseline and 93% with the agent.

| Investigations | Statuses | Confident errors | Unstable conclusions | Robustness check (by agent) | Wrong conclusions downgraded | Agent changed top-1 (helped / hurt) | Escalated |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 117 | complete 110, partial 7 | 1% | 29% | 100% (100%) | 0 of 7 | 0 (0 / 0) | 16% |

| Confidence | Investigations | Top-1 accuracy |
| --- | --- | --- |
| high | 51 | 98% |
| medium | 30 | 93% |
| low | 15 | 73% |

| Cost per investigation (USD) | At Standard prices | Latency (s) | Tool calls | Verifier violations (final / rejected) |
| --- | --- | --- | --- | --- |
| 0.003691 | 0.065761 | 94.35 | 10.68 | 0 / 5 |

| Stage | Investigations | Calls | Input | Cached | Output | Reasoning | Cost USD | At Standard prices | Mean latency (s) | Cache hit rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| investigation | 98 | 523 | 9017326 | 6694739 | 630869 | 425734 | 0.371821978 | 6.58863785 | 92.19 | 74% |
| escalation | 19 | 88 | 1390479 | 1064566 | 126665 | 97783 | 0.060053432 | 1.10540240 | 105.53 | 77% |

| Fault type | Baseline top-1 | Agent top-1 | Baseline top-3 | Agent top-3 | Agent cost at Standard (USD) | Agent latency (s) | Escalated |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cannibalization | 69% | 69% | 77% | 77% | 0.076577 | 115.81 | 9% |
| cpa_drift | 77% | 77% | 77% | 85% | 0.073578 | 103.38 | 9% |
| fee_increase | 92% | 92% | 92% | 92% | 0.060028 | 90.38 | 0% |
| healthy | n/a | n/a | n/a | n/a | 0.066827 | 99.35 | 19% |
| mix_shift | 85% | 85% | 85% | 85% | 0.068495 | 77.67 | 0% |
| refund_spike | 62% | 62% | 69% | 69% | 0.061059 | 79.31 | 0% |
| stockout_on_promoted | 100% | 100% | 100% | 100% | 0.069614 | 99.25 | 0% |
| supplier_cost_increase | 100% | 100% | 100% | 100% | 0.064161 | 85.16 | 0% |
| tracking_break | 100% | 100% | 100% | 100% | 0.052846 | 95.74 | 100% |

## Scenarios that failed

- `dev-cannibalization-01` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): attribution driver. Primary: cannibalization campaign:179d5e19-460a-5491-af07-4d0469ef8d60; largest negative driver: volume (expected ad_spend).
- `dev-cannibalization-02` (cannibalization magnitude 0.80 from day 70 (2026-08-10)): attribution driver. Primary: cannibalization campaign:03814fb3-6305-5054-ae83-f447b053ed6a; largest negative driver: volume (expected ad_spend).
- `dev-cannibalization-04` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: volume (expected ad_spend).
- `dev-cannibalization-06` (cannibalization magnitude 0.80 from day 70 (2026-08-10)): attribution driver. Primary: cannibalization campaign:acbabd40-34ef-5e9c-8d3b-3da07d8494ff; largest negative driver: refunds (expected ad_spend).
- `dev-cannibalization-08` (cannibalization magnitude 1.50 from day 84 (2026-08-24)): attribution driver. Primary: cannibalization campaign:87253382-736e-54a3-ac61-d911bc3eb48b; largest negative driver: volume (expected ad_spend).
- `dev-cannibalization-09` (cannibalization (subtle) magnitude 0.30 from day 77 (2026-08-17)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: ad_spend (expected ad_spend).
- `dev-cannibalization-10` (cannibalization magnitude 0.50 from day 63 (2026-08-03)): attribution driver. Primary: cannibalization campaign:98af0504-4bd9-5889-8b07-e15a34654ac6; largest negative driver: mix (expected ad_spend).
- `dev-cannibalization-11` (cannibalization magnitude 0.80 from day 70 (2026-08-10)): wrong top-1, not top-3, attribution driver. Primary: mix_shift store; largest negative driver: refunds (expected ad_spend).
- `dev-cannibalization-13` (cannibalization magnitude 1.50 from day 84 (2026-08-24)): wrong top-1. Primary: cpa_drift campaign:74abae05-1904-5266-98a5-6119b51351e5; largest negative driver: ad_spend (expected ad_spend).
- `dev-cpa_drift-01` (cpa_drift (subtle) magnitude 0.20 from day 84 (2026-08-24)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: refunds (expected volume).
- `dev-cpa_drift-02` (cpa_drift magnitude 0.50 from day 70 (2026-08-10)): wrong top-1, not top-3, attribution driver. Primary: tracking_break campaign:2806491a-3520-5880-979e-69acefe22307; largest negative driver: refunds (expected volume).
- `dev-cpa_drift-04` (cpa_drift (subtle) magnitude 0.20 from day 84 (2026-08-24)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: volume (expected volume).
- `dev-cpa_drift-05` (cpa_drift magnitude 0.35 from day 56 (2026-07-27)): attribution driver. Primary: cpa_drift campaign:0b93532f-379d-513b-b269-413ed5495d79; largest negative driver: mix (expected volume).
- `dev-cpa_drift-06` (cpa_drift magnitude 0.50 from day 70 (2026-08-10)): attribution driver. Primary: cpa_drift campaign:27832651-7068-5724-8dcb-9038bde51bd3; largest negative driver: fixed_costs (expected volume).
- `dev-cpa_drift-07` (cpa_drift magnitude 0.65 from day 63 (2026-08-03)): attribution driver. Primary: cpa_drift campaign:95888aef-a1fe-55f6-90c7-aff0892827a8; largest negative driver: mix (expected volume).
- `dev-cpa_drift-10` (cpa_drift magnitude 0.35 from day 56 (2026-07-27)): attribution driver. Primary: cpa_drift campaign:772ebf21-3d81-582b-ac8e-d4846cb3d9b3; largest negative driver: refunds (expected volume).
- `dev-fee_increase-02` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): attribution driver. Primary: fee_increase product:fe224179-6869-5bad-bf04-11e658f9c55f; largest negative driver: refunds (expected fees).
- `dev-fee_increase-03` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): attribution driver. Primary: fee_increase product:3b155ebd-127a-5b98-882c-8b8a0cf68495; largest negative driver: refunds (expected fees).
- `dev-fee_increase-04` (fee_increase (subtle) magnitude 0.15 from day 79 (2026-08-19)): attribution driver. Primary: fee_increase store; largest negative driver: volume (expected fees).
- `dev-fee_increase-06` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): attribution driver. Primary: fee_increase product:077c15c6-7328-5a1f-b910-1a8b12adaf3f; largest negative driver: refunds (expected fees).
- `dev-fee_increase-08` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): attribution driver. Primary: fee_increase product:2c04d9a7-2fdb-520f-8221-8b06413033f1; largest negative driver: refunds (expected fees).
- `dev-fee_increase-10` (fee_increase magnitude 0.30 from day 61 (2026-08-01)): attribution driver. Primary: fee_increase store; largest negative driver: refunds (expected fees).
- `dev-fee_increase-11` (fee_increase magnitude 0.50 from day 69 (2026-08-09)): wrong top-1, not top-3, attribution driver. Primary: stockout_on_promoted product:7c8133e1-ba3e-56a4-aa45-15c5daaff0df; largest negative driver: volume (expected fees).
- `dev-fee_increase-13` (fee_increase magnitude 1.00 from day 72 (2026-08-12)): attribution driver. Primary: fee_increase product:a233cc8e-9f89-5421-b788-6c946cc0f130; largest negative driver: mix (expected fees).
- `dev-healthy-08` (healthy store, no fault): false alert. Primary: refund_spike product:52c93995-619f-5013-b7ce-64569c53fd51; largest negative driver: volume.
- `dev-healthy-28` (healthy store, no fault): false alert. Primary: mix_shift store; largest negative driver: mix.
- `dev-mix_shift-04` (mix_shift (subtle) magnitude 0.15 from day 82 (2026-08-22)): not detected. Primary: mix_shift store; largest negative driver: mix (expected mix).
- `dev-mix_shift-05` (mix_shift magnitude 0.25 from day 59 (2026-07-30)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: refunds (expected mix).
- `dev-mix_shift-09` (mix_shift (subtle) magnitude 0.15 from day 82 (2026-08-22)): wrong top-1, not top-3, attribution driver. Primary: refund_spike product:7e545adc-a9d6-555b-b3cc-8be980e45f31; largest negative driver: refunds (expected mix).
- `dev-mix_shift-11` (mix_shift magnitude 0.35 from day 66 (2026-08-06)): not detected, attribution driver. Primary: mix_shift store; largest negative driver: refunds (expected mix).
- `dev-refund_spike-01` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3, attribution driver. Primary: no incident; largest negative driver: mix (expected refunds).
- `dev-refund_spike-04` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: refunds (expected refunds).
- `dev-refund_spike-05` (refund_spike magnitude 0.10 from day 60 (2026-07-31)): attribution driver. Primary: refund_spike product:ad0b6925-0c50-5390-bae9-47e23dc58116; largest negative driver: mix (expected refunds).
- `dev-refund_spike-09` (refund_spike (subtle) magnitude 0.05 from day 75 (2026-08-15)): not detected, wrong top-1, not top-3, attribution driver. Primary: mix_shift store; largest negative driver: volume (expected refunds).
- `dev-refund_spike-10` (refund_spike magnitude 0.10 from day 60 (2026-07-31)): not detected, wrong top-1, not top-3. Primary: no incident; largest negative driver: refunds (expected refunds).
- `dev-refund_spike-11` (refund_spike magnitude 0.15 from day 68 (2026-08-08)): not detected, wrong top-1. Primary: mix_shift store; largest negative driver: refunds (expected refunds).
- `dev-stockout_on_promoted-09` (stockout_on_promoted (subtle) magnitude 1 from day 88 (2026-08-28)): attribution driver. Primary: stockout_on_promoted product:3aac1a15-8edf-5d8c-93a9-e7e3fd82a6aa; largest negative driver: mix (expected volume).
- `dev-stockout_on_promoted-13` (stockout_on_promoted magnitude 1 from day 78 (2026-08-18)): attribution driver. Primary: stockout_on_promoted product:0c220d11-0d0e-5fae-8049-40c72a116812; largest negative driver: mix (expected volume).
- `dev-supplier_cost_increase-01` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): attribution driver. Primary: supplier_cost_increase product:0f0eefd0-256d-5a8f-80e9-cbd064e654a3; largest negative driver: mix (expected unit_cost).
- `dev-supplier_cost_increase-02` (supplier_cost_increase magnitude 0.20 from day 67 (2026-08-07)): attribution driver. Primary: supplier_cost_increase product:e30c7706-8e2c-591e-86da-084ecb390d0d; largest negative driver: ad_spend (expected unit_cost).
- `dev-supplier_cost_increase-04` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): attribution driver. Primary: supplier_cost_increase product:0ac43d29-fed1-57f9-945c-26b65530ff04; largest negative driver: volume (expected unit_cost).
- `dev-supplier_cost_increase-05` (supplier_cost_increase magnitude 0.10 from day 58 (2026-07-29)): attribution driver. Primary: supplier_cost_increase product:715f5814-8038-5158-80b2-9d795285cc6f; largest negative driver: refunds (expected unit_cost).
- `dev-supplier_cost_increase-09` (supplier_cost_increase (subtle) magnitude 0.05 from day 80 (2026-08-20)): attribution driver. Primary: supplier_cost_increase product:09e6cf49-93d9-5600-a988-4b97499eb5b9; largest negative driver: refunds (expected unit_cost).
- `dev-supplier_cost_increase-10` (supplier_cost_increase magnitude 0.10 from day 58 (2026-07-29)): attribution driver. Primary: supplier_cost_increase product:234d9679-b0f5-5926-8827-d848996425e7; largest negative driver: ad_spend (expected unit_cost).
- `dev-supplier_cost_increase-11` (supplier_cost_increase magnitude 0.20 from day 67 (2026-08-07)): attribution driver. Primary: supplier_cost_increase product:3ad5b291-2829-50e7-896c-7b1de2c47578; largest negative driver: volume (expected unit_cost).
- `dev-supplier_cost_increase-12` (supplier_cost_increase magnitude 0.30 from day 74 (2026-08-14)): attribution driver. Primary: supplier_cost_increase product:917b752e-204d-5529-8ef0-90954db98319; largest negative driver: refunds (expected unit_cost).
- `dev-supplier_cost_increase-13` (supplier_cost_increase magnitude 0.50 from day 62 (2026-08-02)): attribution driver. Primary: supplier_cost_increase product:ce27ed9c-099b-5491-b8ac-53fec920e698; largest negative driver: volume (expected unit_cost).
