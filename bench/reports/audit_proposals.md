# Audit proposals (for human review)

Generated from the `dev` agent run of 2026-10-29T16:03:58+00:00. Nothing here is applied automatically: a detector change is tuned on `dev`, then evaluated on a new hold-out.

## Where the investigation corrected the detectors

None.

## Where the investigation overturned a correct ranking (agent issues)

None.

## Where the detectors and the investigation were both wrong

- 2 `refund_spike` scenario(s) ranked `mix_shift` first by both. Proposal: a detector or symptom that separates `refund_spike` from `mix_shift`. Scenarios: `dev-refund_spike-09`, `dev-refund_spike-11`.
- 1 `cannibalization` scenario(s) ranked `cpa_drift` first by both. Proposal: a detector or symptom that separates `cannibalization` from `cpa_drift`. Scenarios: `dev-cannibalization-13`.
- 1 `cannibalization` scenario(s) ranked `mix_shift` first by both. Proposal: a detector or symptom that separates `cannibalization` from `mix_shift`. Scenarios: `dev-cannibalization-11`.
- 1 `cpa_drift` scenario(s) ranked `tracking_break` first by both. Proposal: a detector or symptom that separates `cpa_drift` from `tracking_break`. Scenarios: `dev-cpa_drift-02`.
- 1 `fee_increase` scenario(s) ranked `stockout_on_promoted` first by both. Proposal: a detector or symptom that separates `fee_increase` from `stockout_on_promoted`. Scenarios: `dev-fee_increase-11`.
- 1 `mix_shift` scenario(s) ranked `refund_spike` first by both. Proposal: a detector or symptom that separates `mix_shift` from `refund_spike`. Scenarios: `dev-mix_shift-09`.

## Audit findings by fault type

| Fault type | Finding | Count |
| --- | --- | --- |
| cannibalization | data_gap | 1 |
| cannibalization | method_mismatch | 2 |
| cannibalization | reconciliation_gap | 1 |
| cannibalization | unstable_conclusion | 4 |
| cannibalization | weak_evidence | 4 |
| cannibalization | window_contamination | 2 |
| cpa_drift | reconciliation_gap | 5 |
| cpa_drift | unstable_conclusion | 2 |
| cpa_drift | weak_evidence | 4 |
| fee_increase | unstable_conclusion | 5 |
| fee_increase | weak_evidence | 4 |
| healthy | data_gap | 1 |
| healthy | method_mismatch | 3 |
| healthy | reconciliation_gap | 2 |
| healthy | unstable_conclusion | 13 |
| healthy | weak_evidence | 11 |
| healthy | window_contamination | 1 |
| mix_shift | weak_evidence | 2 |
| refund_spike | unstable_conclusion | 3 |
| refund_spike | weak_evidence | 6 |
| stockout_on_promoted | unstable_conclusion | 1 |
| stockout_on_promoted | weak_evidence | 1 |
| supplier_cost_increase | reconciliation_gap | 2 |
| supplier_cost_increase | unstable_conclusion | 3 |
| supplier_cost_increase | weak_evidence | 7 |
| tracking_break | reconciliation_gap | 4 |
| tracking_break | unstable_conclusion | 7 |

## Unstable conclusions by fault type

| Fault type | Count |
| --- | --- |
| cannibalization | 3 |
| cpa_drift | 1 |
| fee_increase | 5 |
| healthy | 12 |
| refund_spike | 3 |
| stockout_on_promoted | 1 |
| supplier_cost_increase | 2 |
| tracking_break | 7 |
