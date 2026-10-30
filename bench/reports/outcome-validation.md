# Outcome validation

Run `outcome-validation-20261030T212611Z`: 52 actions on dev scenarios (a pause, a budget cut of 30% or a raise of 20% on the store's largest campaign, executed on the simulator 14 days before the data end), measured after 7 days by synthetic control, against the true effect: the same store without the action.

| Measured | Abstained | P10-P90 coverage (target 80%) | Bias of P50 | Mean abs error | Median abs error |
| --- | --- | --- | --- | --- | --- |
| 48 | 4 (8%) | 69% | -54.58 | 482.88 | 304.57 |

Intervals: the measured P10-P90 holds the truth 69% of the time against the 80% target; they are too narrow, most for pause (44%).

Threshold 0.5: refuted on these runs. The 4 estimates it withheld hold the truth 100% of the time (mean abs error 253.18), the 48 it lets through 69% (482.88): a weak pre-period fit does not predict a wrong estimate, and the misses are among the estimates it reports. With 4 estimates above it, the evidence is thin.

Abstentions: the pre-period fit is too weak (4).

By action (measured only):

| Action | n | Coverage | Bias | Mean abs error |
| --- | --- | --- | --- | --- |
| pause | 16 | 44% | 98.59 | 684.92 |
| budget -30% | 15 | 87% | -260.48 | 464.54 |
| budget +20% | 17 | 76% | -17.07 | 308.92 |

The weak-fit threshold: every estimate, including those the threshold withheld, by the pre-period's relative error (daily RMSE over the mean absolute level). The threshold is 0.5: estimates above it are not reported.

| Relative error | n | Coverage | Bias | Mean abs error |
| --- | --- | --- | --- | --- |
| 0.0 to 0.25 | 13 | 85% | -231.67 | 357.99 |
| 0.25 to 0.5 | 35 | 63% | 11.19 | 529.27 |
| 0.5 to 1.0 | 4 | 100% | 194.97 | 253.18 |

| Scenario | Action | Status | Relative error | Measured P10 / P50 / P90 | Truth |
| --- | --- | --- | --- | --- | --- |
| dev-cannibalization-01 | pause | measured | 0.31 | -2243 / -1796 / -1475 | -2350 |
| dev-cannibalization-04 | budget -30% | measured | 0.33 | -723 / -492 / -207 | -260 |
| dev-cannibalization-07 | budget +20% | measured | 0.46 | -400 / 218 / 911 | -737 |
| dev-cannibalization-10 | pause | measured | 0.42 | -934 / -661 / -212 | -785 |
| dev-cannibalization-13 | budget -30% | measured | 0.30 | -91 / 662 / 1524 | -785 |
| dev-cpa_drift-03 | budget +20% | measured | 0.25 | 160 / 1068 / 1522 | 834 |
| dev-cpa_drift-06 | pause | measured | 0.37 | -795 / -529 / -267 | -915 |
| dev-cpa_drift-09 | budget -30% | measured | 0.24 | -1375 / -627 / 323 | -637 |
| dev-cpa_drift-12 | budget +20% | measured | 0.30 | -1259 / 289 / 1851 | -120 |
| dev-fee_increase-02 | pause | measured | 0.17 | -3741 / -3150 / -2422 | -294 |
| dev-fee_increase-05 | budget -30% | measured | 0.21 | -747 / -214 / 352 | -81 |
| dev-fee_increase-08 | budget +20% | measured | 0.27 | -1152 / -521 / 58 | 76 |
| dev-fee_increase-11 | pause | measured | 0.28 | -609 / 440 / 1036 | -743 |
| dev-healthy-01 | budget -30% | measured | 0.25 | -1722 / -867 / -432 | -749 |
| dev-healthy-04 | budget +20% | measured | 0.31 | -146 / 7 / 233 | -57 |
| dev-healthy-07 | pause | measured | 0.24 | -1757 / -1569 / -1411 | -2276 |
| dev-healthy-10 | budget -30% | abstained | 0.50 | the pre-period fit is too weak | 1106 |
| dev-healthy-13 | budget +20% | measured | 0.30 | -622 / 129 / 516 | 496 |
| dev-healthy-16 | pause | abstained | 0.63 | the pre-period fit is too weak | -980 |
| dev-healthy-19 | budget -30% | measured | 0.20 | -2284 / -1465 / -737 | -1172 |
| dev-healthy-22 | budget +20% | measured | 0.25 | 1442 / 1719 / 2150 | 1403 |
| dev-healthy-25 | pause | measured | 0.24 | -4154 / -3161 / -2420 | -2978 |
| dev-healthy-28 | budget -30% | abstained | 0.54 | the pre-period fit is too weak | -716 |
| dev-healthy-31 | budget +20% | measured | 0.32 | -1232 / -822 / -307 | -708 |
| dev-healthy-34 | pause | measured | 0.27 | -3187 / -2275 / -1779 | -3374 |
| dev-healthy-37 | budget -30% | measured | 0.25 | -878 / -340 / 148 | -341 |
| dev-healthy-40 | budget +20% | measured | 0.23 | -767 / -4 / 506 | -65 |
| dev-healthy-43 | pause | measured | 0.34 | -2770 / -2045 / -1655 | -3519 |
| dev-healthy-46 | budget -30% | measured | 0.27 | -838 / -411 / -24 | -36 |
| dev-healthy-49 | budget +20% | measured | 0.19 | -1028 / -131 / 340 | -173 |
| dev-mix_shift-02 | pause | measured | 0.28 | -616 / -310 / 136 | -704 |
| dev-mix_shift-05 | budget -30% | measured | 0.26 | -950 / -443 / 358 | -84 |
| dev-mix_shift-08 | budget +20% | measured | 0.42 | -359 / -7 / 280 | 158 |
| dev-mix_shift-11 | pause | measured | 0.27 | -1518 / -1252 / -986 | -1196 |
| dev-refund_spike-01 | budget -30% | measured | 0.28 | -302 / -55 / 561 | -128 |
| dev-refund_spike-04 | budget +20% | measured | 0.19 | 342 / 1568 / 3011 | 1569 |
| dev-refund_spike-07 | pause | measured | 0.34 | -1816 / -1599 / -1010 | -1423 |
| dev-refund_spike-10 | budget -30% | measured | 0.26 | -2033 / -1415 / -300 | 308 |
| dev-refund_spike-13 | budget +20% | measured | 0.41 | -474 / 110 / 934 | 809 |
| dev-stockout_on_promoted-03 | pause | measured | 0.25 | -2067 / -908 / 203 | 426 |
| dev-stockout_on_promoted-06 | budget -30% | measured | 0.30 | -1892 / -1265 / -634 | -878 |
| dev-stockout_on_promoted-09 | budget +20% | measured | 0.24 | -836 / -102 / 293 | 94 |
| dev-stockout_on_promoted-12 | pause | abstained | 0.61 | the pre-period fit is too weak | 508 |
| dev-supplier_cost_increase-02 | budget -30% | measured | 0.29 | -1813 / -445 / 405 | 161 |
| dev-supplier_cost_increase-05 | budget +20% | measured | 0.30 | 502 / 1297 / 1948 | 898 |
| dev-supplier_cost_increase-08 | pause | measured | 0.29 | -2715 / -2111 / -1617 | -2025 |
| dev-supplier_cost_increase-11 | budget -30% | measured | 0.33 | -562 / -312 / 54 | -131 |
| dev-tracking_break-01 | budget +20% | measured | 0.26 | 188 / 549 / 997 | 1129 |
| dev-tracking_break-04 | pause | measured | 0.43 | -3127 / -1474 / -1077 | -1555 |
| dev-tracking_break-07 | budget -30% | measured | 0.25 | -4061 / -2755 / -1438 | -1724 |
| dev-tracking_break-10 | budget +20% | measured | 0.16 | -401 / -249 / -29 | -197 |
| dev-tracking_break-13 | pause | measured | 0.44 | -2303 / -1483 / -974 | -1749 |
