# Briefing costs

Run `briefing-costs-20261030T175145Z`: every golden scenario's daily brief, weekly report and monthly review, after detection and its alerts, generated live with production routing (Spark, low effort). The model writes only the narrative; sections and numbers come from facts, so a briefing whose narrative fails is still complete (facts only).

| Type | Briefings | Narrated | Mean cost USD | Max cost USD | Mean input tokens | Mean output tokens | Mean attempts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| daily | 14 | 14 | 0.006892 | 0.008285 | 1474 | 1404 | 1 |
| weekly | 14 | 14 | 0.013618 | 0.015109 | 5567 | 1762 | 1 |
| monthly | 14 | 14 | 0.013848 | 0.016548 | 5961 | 1686 | 1 |

Total cost of the run: USD 0.480997 (the spend ledger, failed calls included: USD 0.481002).

| Scenario | Type | Status | Attempts | Input tokens | Output tokens | Cost USD | Facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| golden-cannibalization | daily | narrated | 1 | 1197 | 1093 | 0.005313 | 4 |
| golden-cannibalization | weekly | narrated | 1 | 5589 | 1546 | 0.012728 | 334 |
| golden-cannibalization | monthly | narrated | 1 | 6012 | 1605 | 0.014336 | 725 |
| golden-cpa_drift-with-decision | daily | narrated | 1 | 1751 | 1341 | 0.007060 | 7 |
| golden-cpa_drift-with-decision | weekly | narrated | 1 | 5856 | 1461 | 0.012701 | 294 |
| golden-cpa_drift-with-decision | monthly | narrated | 1 | 6168 | 2175 | 0.016125 | 630 |
| golden-cpa_drift | daily | narrated | 1 | 1762 | 1512 | 0.007800 | 7 |
| golden-cpa_drift | weekly | narrated | 1 | 5499 | 1686 | 0.013211 | 292 |
| golden-cpa_drift | monthly | narrated | 1 | 5917 | 1236 | 0.011821 | 628 |
| golden-fee_increase | daily | narrated | 1 | 1601 | 1608 | 0.007866 | 7 |
| golden-fee_increase | weekly | narrated | 1 | 5509 | 1715 | 0.013347 | 216 |
| golden-fee_increase | monthly | narrated | 1 | 5916 | 1397 | 0.012504 | 420 |
| golden-injection | daily | narrated | 1 | 1204 | 1424 | 0.006588 | 4 |
| golden-injection | weekly | narrated | 1 | 5503 | 1662 | 0.013114 | 195 |
| golden-injection | monthly | narrated | 1 | 5920 | 1681 | 0.013716 | 366 |
| golden-mix_shift | daily | narrated | 1 | 2063 | 1339 | 0.007441 | 10 |
| golden-mix_shift | weekly | narrated | 1 | 5576 | 2110 | 0.015109 | 292 |
| golden-mix_shift | monthly | narrated | 1 | 5985 | 1784 | 0.014235 | 606 |
| golden-refund_spike | daily | narrated | 1 | 1781 | 1288 | 0.006731 | 7 |
| golden-refund_spike | weekly | narrated | 1 | 5675 | 2037 | 0.014923 | 321 |
| golden-refund_spike | monthly | narrated | 1 | 6089 | 1700 | 0.014008 | 690 |
| golden-short-history-decision | daily | narrated | 1 | 1205 | 1790 | 0.008285 | 4 |
| golden-short-history-decision | weekly | narrated | 1 | 5809 | 1794 | 0.014057 | 237 |
| golden-short-history-decision | monthly | narrated | 1 | 6081 | 1670 | 0.013870 | 452 |
| golden-stockout_on_promoted | daily | narrated | 1 | 1887 | 1364 | 0.007187 | 8 |
| golden-stockout_on_promoted | weekly | narrated | 1 | 5742 | 1739 | 0.013740 | 244 |
| golden-stockout_on_promoted | monthly | narrated | 1 | 6149 | 1966 | 0.015213 | 514 |
| golden-supplier_cost_increase | daily | narrated | 1 | 1204 | 1074 | 0.005100 | 4 |
| golden-supplier_cost_increase | weekly | narrated | 1 | 5151 | 2155 | 0.014769 | 212 |
| golden-supplier_cost_increase | monthly | narrated | 1 | 5568 | 1102 | 0.010815 | 427 |
| golden-tracking_break | daily | narrated | 1 | 1375 | 1522 | 0.007218 | 4 |
| golden-tracking_break | weekly | narrated | 1 | 5349 | 1876 | 0.013831 | 325 |
| golden-tracking_break | monthly | narrated | 1 | 5749 | 1115 | 0.011097 | 694 |
| golden-underfunded_campaign | daily | narrated | 1 | 1205 | 1657 | 0.007579 | 4 |
| golden-underfunded_campaign | weekly | narrated | 1 | 5585 | 1762 | 0.013641 | 236 |
| golden-underfunded_campaign | monthly | narrated | 1 | 5994 | 2219 | 0.016095 | 451 |
| healthy-a | daily | narrated | 1 | 1204 | 1301 | 0.006065 | 4 |
| healthy-a | weekly | narrated | 1 | 5452 | 1509 | 0.012400 | 221 |
| healthy-a | monthly | narrated | 1 | 5857 | 1646 | 0.013488 | 447 |
| healthy-b | daily | narrated | 1 | 1204 | 1344 | 0.006248 | 4 |
| healthy-b | weekly | narrated | 1 | 5641 | 1612 | 0.013074 | 371 |
| healthy-b | monthly | narrated | 1 | 6044 | 2311 | 0.016548 | 795 |
