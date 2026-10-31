# Outcome validation (`outcomes_v1`)

Runs `outcome-validation-outcomes_v1-cut-20261031T022207Z-part1of2`, `outcome-validation-outcomes_v1-cut-20261031T022308Z-part2of2`, `outcome-validation-outcomes_v1-pause-20261031T022007Z-part1of2`, `outcome-validation-outcomes_v1-pause-20261031T022107Z-part2of2`, `outcome-validation-outcomes_v1-raise-20261031T022409Z-part1of2`, `outcome-validation-outcomes_v1-raise-20261031T022510Z-part2of2`: 210 actions on `outcomes_v1` scenarios (a pause, a budget cut of 30% or a raise of 20% on the store's largest campaign, executed on the simulator 14 days before the data end), measured after 7 days by synthetic control, against the true effect: the same store without the action.

| Measured | Abstained | P10-P90 coverage (target 80%) | Without calibration | Bias of P50 | Mean abs error | Median abs error |
| --- | --- | --- | --- | --- | --- | --- |
| 189 | 21 (10%) | 82% | 74% | 43.38 | 524.81 | 312.61 |

Intervals: the reported P10-P90 holds the truth 82% of the time against the 80% target (74% without the calibration); the lowest is budget +20% (81%).

Threshold 0.5: it withholds 21 of 210 estimates (10%). Made anyway, they would hold the truth 57% of the time (mean abs error 718.46), against 82% (524.81) for those it reports: here the estimates it withholds are worse than those it reports.

Abstentions: the pre-period fit is too weak (21).

By action (measured only):

| Action | n | Coverage | Without calibration | Bias | Mean abs error |
| --- | --- | --- | --- | --- | --- |
| pause | 63 | 82% | 70% | 52.04 | 552.71 |
| budget -30% | 63 | 84% | 75% | 38.86 | 513.48 |
| budget +20% | 63 | 81% | 76% | 39.25 | 508.25 |

The weak-fit threshold: every estimate, including those the threshold withheld (as they would be reported, calibration included), by the pre-period's relative error (daily RMSE over the mean absolute level). The threshold is 0.5: estimates above it are not reported.

| Relative error | n | Coverage | Bias | Mean abs error |
| --- | --- | --- | --- | --- |
| 0.0 to 0.25 | 27 | 78% | -381.33 | 512.02 |
| 0.25 to 0.5 | 162 | 83% | 114.17 | 526.94 |
| 0.5 to 1.0 | 21 | 57% | 672.09 | 718.46 |

| Scenario | Action | Status | Relative error | Reported P10 / P50 / P90 | Uncalibrated P10 / P90 | Truth |
| --- | --- | --- | --- | --- | --- | --- |
| outcomes_v1-cannibalization-01 | budget -30% | measured | 0.31 | -465 / 1046 / 2132 | -75 / 1742 | 1250 |
| outcomes_v1-cannibalization-03 | budget -30% | measured | 0.26 | -70 / 1031 / 2157 | 265 / 1822 | 1952 |
| outcomes_v1-cannibalization-05 | budget -30% | measured | 0.23 | -2018 / -720 / 271 | -1674 / -73 | -982 |
| outcomes_v1-cpa_drift-02 | budget -30% | measured | 0.31 | -485 / -180 / 466 | -343 / 323 | -27 |
| outcomes_v1-cpa_drift-04 | budget -30% | abstained | 0.59 | the pre-period fit is too weak | 317 / 1060 | 290 |
| outcomes_v1-fee_increase-01 | budget -30% | measured | 0.38 | -429 / 248 / 1283 | -172 / 1026 | 609 |
| outcomes_v1-fee_increase-03 | budget -30% | measured | 0.28 | -2950 / -1436 / -451 | -2574 / -826 | -1040 |
| outcomes_v1-fee_increase-05 | budget -30% | measured | 0.39 | -1747 / -721 / 163 | -1460 / -124 | 41 |
| outcomes_v1-healthy-02 | budget -30% | measured | 0.36 | -1739 / -450 / 1062 | -1318 / 641 | -745 |
| outcomes_v1-healthy-04 | budget -30% | measured | 0.24 | -1630 / -1156 / -857 | -1514 / -973 | -385 |
| outcomes_v1-healthy-06 | budget -30% | measured | 0.25 | -2108 / -1000 / 493 | -1718 / 102 | -108 |
| outcomes_v1-healthy-08 | budget -30% | measured | 0.25 | -628 / 46 / 1192 | -354 / 919 | -254 |
| outcomes_v1-healthy-10 | budget -30% | measured | 0.36 | -792 / -123 / 508 | -597 / 313 | -323 |
| outcomes_v1-healthy-12 | budget -30% | measured | 0.25 | -2410 / -767 / 321 | -2000 / -89 | -720 |
| outcomes_v1-healthy-14 | budget -30% | measured | 0.23 | 534 / 1165 / 1602 | 694 / 1441 | 1029 |
| outcomes_v1-healthy-16 | budget -30% | measured | 0.24 | -327 / 988 / 2265 | 62 / 1876 | 1464 |
| outcomes_v1-healthy-18 | budget -30% | measured | 0.30 | -505 / -45 / 730 | -319 / 544 | 517 |
| outcomes_v1-healthy-20 | budget -30% | abstained | 0.52 | the pre-period fit is too weak | 487 / 1711 | -687 |
| outcomes_v1-healthy-22 | budget -30% | measured | 0.28 | -352 / 268 / 778 | -182 / 608 | 22 |
| outcomes_v1-healthy-24 | budget -30% | measured | 0.35 | -923 / -312 / 278 | -743 / 98 | -411 |
| outcomes_v1-healthy-26 | budget -30% | measured | 0.43 | -2396 / -1516 / -936 | -2176 / -1155 | -119 |
| outcomes_v1-healthy-28 | budget -30% | measured | 0.28 | -2057 / -1098 / -316 | -1796 / -577 | -1416 |
| outcomes_v1-healthy-30 | budget -30% | measured | 0.23 | -1675 / -394 / 808 | -1302 / 435 | -504 |
| outcomes_v1-mix_shift-02 | budget -30% | measured | 0.26 | -445 / 333 / 732 | -268 / 555 | -192 |
| outcomes_v1-mix_shift-04 | budget -30% | measured | 0.27 | -1921 / -1161 / -156 | -1656 / -421 | -1334 |
| outcomes_v1-refund_spike-01 | budget -30% | measured | 0.27 | 237 / 2141 / 4829 | 927 / 4140 | 748 |
| outcomes_v1-refund_spike-03 | budget -30% | abstained | 0.70 | the pre-period fit is too weak | -485 / 268 | 111 |
| outcomes_v1-refund_spike-05 | budget -30% | measured | 0.32 | -2017 / -950 / 221 | -1681 / -115 | -1659 |
| outcomes_v1-stockout_on_promoted-02 | budget -30% | measured | 0.38 | -1820 / -1043 / -198 | -1576 / -442 | -1264 |
| outcomes_v1-stockout_on_promoted-04 | budget -30% | measured | 0.28 | -1528 / -754 / -172 | -1324 / -376 | 251 |
| outcomes_v1-supplier_cost_increase-01 | budget -30% | measured | 0.34 | -3303 / -1736 / -449 | -2874 / -878 | -854 |
| outcomes_v1-supplier_cost_increase-03 | budget -30% | measured | 0.30 | -1341 / -371 / 709 | -1033 / 401 | -673 |
| outcomes_v1-supplier_cost_increase-05 | budget -30% | measured | 0.19 | -1545 / -883 / 492 | -1239 / 186 | -313 |
| outcomes_v1-tracking_break-02 | budget -30% | measured | 0.29 | 56 / 1465 / 2567 | 433 / 2190 | 1411 |
| outcomes_v1-tracking_break-04 | budget -30% | measured | 0.42 | -495 / 113 / 610 | -329 / 445 | -310 |
| outcomes_v1-cannibalization-02 | budget -30% | measured | 0.31 | -704 / -107 / 524 | -520 / 339 | 76 |
| outcomes_v1-cannibalization-04 | budget -30% | measured | 0.29 | -1534 / -568 / 889 | -1170 / 525 | -736 |
| outcomes_v1-cpa_drift-01 | budget -30% | measured | 0.28 | -2937 / -1473 / 145 | -2474 / -317 | -1381 |
| outcomes_v1-cpa_drift-03 | budget -30% | abstained | 0.57 | the pre-period fit is too weak | 105 / 1021 | -309 |
| outcomes_v1-cpa_drift-05 | budget -30% | measured | 0.26 | 366 / 411 / 437 | 376 / 426 | 154 |
| outcomes_v1-fee_increase-02 | budget -30% | measured | 0.26 | -1558 / -834 / -41 | -1330 / -268 | -828 |
| outcomes_v1-fee_increase-04 | budget -30% | measured | 0.26 | -2247 / -569 / 536 | -1829 / 118 | -3803 |
| outcomes_v1-healthy-01 | budget -30% | measured | 0.42 | -774 / 320 / 1333 | -458 / 1017 | 395 |
| outcomes_v1-healthy-03 | budget -30% | measured | 0.32 | -872 / 176 / 1684 | -488 / 1300 | 52 |
| outcomes_v1-healthy-05 | budget -30% | measured | 0.35 | -270 / 43 / 319 | -182 / 231 | 133 |
| outcomes_v1-healthy-07 | budget -30% | measured | 0.32 | -1679 / -1207 / -429 | -1491 / -617 | -816 |
| outcomes_v1-healthy-09 | budget -30% | abstained | 0.53 | the pre-period fit is too weak | -168 / 670 | -682 |
| outcomes_v1-healthy-11 | budget -30% | measured | 0.35 | -1263 / -612 / 563 | -989 / 289 | -1114 |
| outcomes_v1-healthy-13 | budget -30% | measured | 0.23 | -634 / 292 / 1365 | -334 / 1065 | 666 |
| outcomes_v1-healthy-15 | budget -30% | measured | 0.42 | -2240 / -538 / 448 | -1836 / 45 | -676 |
| outcomes_v1-healthy-17 | budget -30% | measured | 0.26 | -1062 / -2 / 920 | -764 / 623 | 253 |
| outcomes_v1-healthy-19 | budget -30% | measured | 0.22 | -2545 / -1256 / -41 | -2169 / -417 | 292 |
| outcomes_v1-healthy-21 | budget -30% | measured | 0.22 | -627 / 423 / 1998 | -233 / 1604 | 175 |
| outcomes_v1-healthy-23 | budget -30% | measured | 0.31 | 218 / 1094 / 1933 | 475 / 1675 | 1238 |
| outcomes_v1-healthy-25 | budget -30% | measured | 0.33 | -555 / 214 / 740 | -361 / 545 | -66 |
| outcomes_v1-healthy-27 | budget -30% | measured | 0.32 | -990 / 321 / 1522 | -613 / 1144 | 9 |
| outcomes_v1-healthy-29 | budget -30% | measured | 0.43 | -989 / -0 / 1360 | -636 / 1007 | 315 |
| outcomes_v1-mix_shift-01 | budget -30% | abstained | 0.50 | the pre-period fit is too weak | -612 / 73 | -630 |
| outcomes_v1-mix_shift-03 | budget -30% | measured | 0.29 | -931 / -194 / 663 | -692 / 423 | 3 |
| outcomes_v1-mix_shift-05 | budget -30% | measured | 0.26 | -854 / 48 / 1065 | -565 / 777 | -131 |
| outcomes_v1-refund_spike-02 | budget -30% | measured | 0.36 | -962 / 32 / 1549 | -584 / 1172 | -1966 |
| outcomes_v1-refund_spike-04 | budget -30% | measured | 0.28 | -658 / 193 / 830 | -434 / 607 | 460 |
| outcomes_v1-stockout_on_promoted-01 | budget -30% | measured | 0.31 | -546 / 493 / 1547 | -232 / 1232 | -522 |
| outcomes_v1-stockout_on_promoted-03 | budget -30% | measured | 0.28 | -1847 / -1104 / -426 | -1633 / -639 | 505 |
| outcomes_v1-stockout_on_promoted-05 | budget -30% | abstained | 0.63 | the pre-period fit is too weak | 805 / 1825 | 1038 |
| outcomes_v1-supplier_cost_increase-02 | budget -30% | measured | 0.37 | -2114 / -800 / 46 | -1790 / -279 | -1224 |
| outcomes_v1-supplier_cost_increase-04 | budget -30% | measured | 0.28 | -1558 / -540 / 514 | -1247 / 203 | -1195 |
| outcomes_v1-tracking_break-01 | budget -30% | measured | 0.47 | -1778 / -769 / 611 | -1419 / 252 | -915 |
| outcomes_v1-tracking_break-03 | budget -30% | measured | 0.35 | -142 / 631 / 1221 | 62 / 1016 | -276 |
| outcomes_v1-tracking_break-05 | budget -30% | measured | 0.44 | -1236 / -498 / 355 | -997 / 116 | -1545 |
| outcomes_v1-cannibalization-01 | pause | measured | 0.31 | -1977 / -612 / 428 | -1635 / 87 | -692 |
| outcomes_v1-cannibalization-03 | pause | measured | 0.26 | -3206 / -2121 / -1019 | -2896 / -1330 | -1251 |
| outcomes_v1-cannibalization-05 | pause | measured | 0.23 | -1868 / -597 / 367 | -1551 / 50 | -940 |
| outcomes_v1-cpa_drift-02 | pause | measured | 0.31 | -1331 / -1037 / -402 | -1199 / -534 | -936 |
| outcomes_v1-cpa_drift-04 | pause | abstained | 0.59 | the pre-period fit is too weak | -547 / 196 | -626 |
| outcomes_v1-fee_increase-01 | pause | measured | 0.38 | -1505 / -796 / 228 | -1259 / -19 | -605 |
| outcomes_v1-fee_increase-03 | pause | measured | 0.28 | -5618 / -4176 / -3227 | -5279 / -3566 | -3536 |
| outcomes_v1-fee_increase-05 | pause | measured | 0.39 | -2474 / -1475 / -636 | -2213 / -897 | -792 |
| outcomes_v1-healthy-02 | pause | measured | 0.36 | -2094 / -850 / 640 | -1706 / 252 | -1115 |
| outcomes_v1-healthy-04 | pause | measured | 0.24 | -2876 / -2356 / -2051 | -2759 / -2168 | -1581 |
| outcomes_v1-healthy-06 | pause | measured | 0.25 | -2432 / -1353 / 110 | -2071 / -251 | -492 |
| outcomes_v1-healthy-08 | pause | measured | 0.25 | -3328 / -2676 / -1550 | -3076 / -1803 | -2632 |
| outcomes_v1-healthy-10 | pause | measured | 0.36 | -1009 / -337 / 155 | -844 / -11 | -638 |
| outcomes_v1-healthy-12 | pause | measured | 0.25 | -5813 / -4162 / -3144 | -5434 / -3523 | -4720 |
| outcomes_v1-healthy-14 | pause | measured | 0.23 | -3776 / -3071 / -2585 | -3607 / -2754 | -3298 |
| outcomes_v1-healthy-16 | pause | measured | 0.24 | -2920 / -1634 / -387 | -2560 / -747 | -826 |
| outcomes_v1-healthy-18 | pause | measured | 0.30 | -1516 / -1071 / -309 | -1344 / -481 | -609 |
| outcomes_v1-healthy-20 | pause | abstained | 0.52 | the pre-period fit is too weak | -1880 / -656 | -3037 |
| outcomes_v1-healthy-22 | pause | measured | 0.28 | -2257 / -1633 / -1149 | -2099 / -1306 | -1879 |
| outcomes_v1-healthy-24 | pause | measured | 0.35 | -3896 / -3332 / -2789 | -3739 / -2946 | -3628 |
| outcomes_v1-healthy-26 | pause | measured | 0.43 | -3459 / -2598 / -2033 | -3256 / -2235 | -1407 |
| outcomes_v1-healthy-28 | pause | measured | 0.28 | -2439 / -1468 / -737 | -2197 / -979 | -1842 |
| outcomes_v1-healthy-30 | pause | measured | 0.23 | -7190 / -6070 / -4768 | -6846 / -5112 | -5837 |
| outcomes_v1-mix_shift-02 | pause | measured | 0.26 | -1027 / -262 / 123 | -864 / -40 | -871 |
| outcomes_v1-mix_shift-04 | pause | measured | 0.27 | -2273 / -1537 / -576 | -2032 / -817 | -1577 |
| outcomes_v1-refund_spike-01 | pause | measured | 0.27 | -870 / 928 / 3617 | -233 / 2980 | -750 |
| outcomes_v1-refund_spike-03 | pause | abstained | 0.70 | the pre-period fit is too weak | -647 / 106 | -163 |
| outcomes_v1-refund_spike-05 | pause | measured | 0.32 | -2209 / -1214 / -138 | -1915 / -432 | -1950 |
| outcomes_v1-stockout_on_promoted-02 | pause | measured | 0.38 | -1640 / -793 / -56 | -1415 / -281 | -1051 |
| outcomes_v1-stockout_on_promoted-04 | pause | measured | 0.28 | -2229 / -1485 / -920 | -2044 / -1106 | -244 |
| outcomes_v1-supplier_cost_increase-01 | pause | measured | 0.34 | -3507 / -2136 / -1005 | -3152 / -1361 | -1166 |
| outcomes_v1-supplier_cost_increase-03 | pause | measured | 0.30 | -2401 / -1408 / -337 | -2108 / -630 | -1736 |
| outcomes_v1-supplier_cost_increase-05 | pause | measured | 0.19 | -3594 / -2913 / -1603 | -3311 / -1886 | -2246 |
| outcomes_v1-tracking_break-02 | pause | measured | 0.29 | -3128 / -1747 / -670 | -2779 / -1019 | -2008 |
| outcomes_v1-tracking_break-04 | pause | measured | 0.42 | -778 / -183 / 302 | -625 / 148 | -861 |
| outcomes_v1-cannibalization-02 | pause | measured | 0.31 | -1247 / -684 / -63 | -1079 / -232 | -534 |
| outcomes_v1-cannibalization-04 | pause | measured | 0.29 | -1530 / -636 / 678 | -1216 / 364 | -848 |
| outcomes_v1-cpa_drift-01 | pause | measured | 0.28 | -4148 / -2721 / -1145 | -3721 / -1571 | -3024 |
| outcomes_v1-cpa_drift-03 | pause | abstained | 0.57 | the pre-period fit is too weak | -580 / 335 | -1129 |
| outcomes_v1-cpa_drift-05 | pause | measured | 0.26 | 440 / 484 / 510 | 450 / 500 | 212 |
| outcomes_v1-fee_increase-02 | pause | measured | 0.26 | -2444 / -1738 / -961 | -2233 / -1172 | -1719 |
| outcomes_v1-fee_increase-04 | pause | measured | 0.26 | -1555 / 91 / 1164 | -1169 / 778 | -3631 |
| outcomes_v1-healthy-01 | pause | measured | 0.42 | -2254 / -1184 / -194 | -1962 / -487 | -1188 |
| outcomes_v1-healthy-03 | pause | measured | 0.32 | -2574 / -1496 / -66 | -2218 / -423 | -1637 |
| outcomes_v1-healthy-05 | pause | measured | 0.35 | -810 / -506 / -234 | -729 / -316 | -360 |
| outcomes_v1-healthy-07 | pause | measured | 0.32 | -1629 / -1170 / -406 | -1456 / -580 | -879 |
| outcomes_v1-healthy-09 | pause | abstained | 0.53 | the pre-period fit is too weak | -1394 / -556 | -1820 |
| outcomes_v1-healthy-11 | pause | measured | 0.35 | -1888 / -1210 / -47 | -1626 / -309 | -1358 |
| outcomes_v1-healthy-13 | pause | measured | 0.23 | -3027 / -2124 / -1073 | -2749 / -1351 | -1498 |
| outcomes_v1-healthy-15 | pause | measured | 0.42 | -2951 / -1243 / -320 | -2577 / -694 | -1533 |
| outcomes_v1-healthy-17 | pause | measured | 0.26 | -1068 / -75 / 769 | -807 / 508 | -25 |
| outcomes_v1-healthy-19 | pause | measured | 0.22 | -3076 / -1855 / -629 | -2729 / -977 | -336 |
| outcomes_v1-healthy-21 | pause | measured | 0.22 | -3814 / -2708 / -1129 | -3433 / -1511 | -2462 |
| outcomes_v1-healthy-23 | pause | measured | 0.31 | -1804 / -814 / 27 | -1544 / -233 | -515 |
| outcomes_v1-healthy-25 | pause | measured | 0.33 | -2646 / -1951 / -1380 | -2466 / -1560 | -2022 |
| outcomes_v1-healthy-27 | pause | measured | 0.32 | -2410 / -1095 / 45 | -2061 / -304 | -1438 |
| outcomes_v1-healthy-29 | pause | measured | 0.43 | -1545 / -563 / 887 | -1199 / 542 | -104 |
| outcomes_v1-mix_shift-01 | pause | abstained | 0.50 | the pre-period fit is too weak | -663 / 23 | -647 |
| outcomes_v1-mix_shift-03 | pause | measured | 0.29 | -3225 / -2465 / -1579 | -2991 / -1813 | -2041 |
| outcomes_v1-mix_shift-05 | pause | measured | 0.26 | -2820 / -2193 / -1240 | -2595 / -1464 | -2511 |
| outcomes_v1-refund_spike-02 | pause | measured | 0.36 | -3608 / -2687 / -1205 | -3267 / -1546 | -4444 |
| outcomes_v1-refund_spike-04 | pause | measured | 0.28 | -3875 / -3101 / -2421 | -3669 / -2628 | -2864 |
| outcomes_v1-stockout_on_promoted-01 | pause | measured | 0.31 | -1750 / -739 / 248 | -1467 / -36 | -2183 |
| outcomes_v1-stockout_on_promoted-03 | pause | measured | 0.28 | -2192 / -1467 / -819 | -1997 / -1014 | 100 |
| outcomes_v1-stockout_on_promoted-05 | pause | abstained | 0.63 | the pre-period fit is too weak | -627 / 393 | -222 |
| outcomes_v1-supplier_cost_increase-02 | pause | measured | 0.37 | -3044 / -1757 / -949 | -2747 / -1246 | -2139 |
| outcomes_v1-supplier_cost_increase-04 | pause | measured | 0.28 | -4922 / -3804 / -2663 | -4601 / -2983 | -4522 |
| outcomes_v1-tracking_break-01 | pause | measured | 0.47 | -2320 / -1282 / 15 | -1988 / -317 | -1397 |
| outcomes_v1-tracking_break-03 | pause | measured | 0.35 | -1277 / -563 / 56 | -1088 / -134 | -1410 |
| outcomes_v1-tracking_break-05 | pause | measured | 0.44 | -2601 / -1877 / -1027 | -2377 / -1250 | -2562 |
| outcomes_v1-cannibalization-01 | budget +20% | measured | 0.31 | -1334 / -27 / 1074 | -994 / 735 | -108 |
| outcomes_v1-cannibalization-03 | budget +20% | measured | 0.26 | -1043 / 28 / 1126 | -737 / 820 | 1084 |
| outcomes_v1-cannibalization-05 | budget +20% | measured | 0.23 | -1998 / -730 / 231 | -1684 / -83 | -1111 |
| outcomes_v1-cpa_drift-02 | budget +20% | measured | 0.31 | -102 / 231 / 824 | 28 / 694 | 349 |
| outcomes_v1-cpa_drift-04 | budget +20% | abstained | 0.59 | the pre-period fit is too weak | 1305 / 2047 | 1164 |
| outcomes_v1-fee_increase-01 | budget +20% | measured | 0.38 | -1227 / -581 / 500 | -984 / 257 | -284 |
| outcomes_v1-fee_increase-03 | budget +20% | measured | 0.28 | 318 / 1770 / 2702 | 654 / 2366 | 2184 |
| outcomes_v1-fee_increase-05 | budget +20% | measured | 0.39 | -1088 / -91 / 745 | -830 / 487 | 783 |
| outcomes_v1-healthy-02 | budget +20% | measured | 0.36 | -1229 / -16 / 1446 | -852 / 1069 | -5 |
| outcomes_v1-healthy-04 | budget +20% | measured | 0.24 | -183 / 281 / 571 | -77 / 464 | 978 |
| outcomes_v1-healthy-06 | budget +20% | measured | 0.25 | -3116 / -2013 / -582 | -2759 / -939 | -948 |
| outcomes_v1-healthy-08 | budget +20% | measured | 0.25 | -495 / 193 / 1550 | -207 / 1262 | 295 |
| outcomes_v1-healthy-10 | budget +20% | measured | 0.36 | -476 / 154 / 637 | -319 / 480 | 318 |
| outcomes_v1-healthy-12 | budget +20% | measured | 0.25 | -1476 / 170 / 1184 | -1101 / 809 | -15 |
| outcomes_v1-healthy-14 | budget +20% | measured | 0.23 | 229 / 857 / 1269 | 375 / 1122 | 820 |
| outcomes_v1-healthy-16 | budget +20% | measured | 0.24 | -1519 / -225 / 1016 | -1162 / 659 | 173 |
| outcomes_v1-healthy-18 | budget +20% | measured | 0.30 | -803 / -343 / 399 | -634 / 230 | 33 |
| outcomes_v1-healthy-20 | budget +20% | abstained | 0.52 | the pre-period fit is too weak | 1185 / 2410 | -229 |
| outcomes_v1-healthy-22 | budget +20% | measured | 0.28 | -530 / 75 / 571 | -375 / 416 | -113 |
| outcomes_v1-healthy-24 | budget +20% | measured | 0.35 | 156 / 708 / 1185 | 301 / 1040 | 502 |
| outcomes_v1-healthy-26 | budget +20% | measured | 0.43 | -1658 / -797 / -236 | -1457 / -436 | 513 |
| outcomes_v1-healthy-28 | budget +20% | measured | 0.28 | -1178 / -241 / 519 | -939 / 279 | -567 |
| outcomes_v1-healthy-30 | budget +20% | measured | 0.23 | -1784 / -668 / 631 | -1443 / 291 | -339 |
| outcomes_v1-mix_shift-02 | budget +20% | measured | 0.26 | -1149 / -381 / -2 | -987 / -163 | -947 |
| outcomes_v1-mix_shift-04 | budget +20% | measured | 0.27 | -913 / -102 / 780 | -675 / 541 | -281 |
| outcomes_v1-refund_spike-01 | budget +20% | measured | 0.27 | 35 / 1826 / 4508 | 665 / 3878 | 69 |
| outcomes_v1-refund_spike-03 | budget +20% | abstained | 0.70 | the pre-period fit is too weak | -585 / 212 | 29 |
| outcomes_v1-refund_spike-05 | budget +20% | measured | 0.32 | -564 / 464 / 1617 | -256 / 1310 | -348 |
| outcomes_v1-stockout_on_promoted-02 | budget +20% | measured | 0.38 | -1048 / -286 / 538 | -824 / 315 | -548 |
| outcomes_v1-stockout_on_promoted-04 | budget +20% | measured | 0.28 | -1548 / -808 / -243 | -1364 / -427 | 548 |
| outcomes_v1-supplier_cost_increase-01 | budget +20% | measured | 0.34 | -1391 / -13 / 1115 | -1037 / 762 | 729 |
| outcomes_v1-supplier_cost_increase-03 | budget +20% | measured | 0.30 | -1119 / -194 / 863 | -840 / 584 | -513 |
| outcomes_v1-supplier_cost_increase-05 | budget +20% | measured | 0.19 | -388 / 248 / 1597 | -108 / 1317 | 585 |
| outcomes_v1-tracking_break-02 | budget +20% | measured | 0.29 | -1393 / 60 / 1143 | -1036 / 785 | -24 |
| outcomes_v1-tracking_break-04 | budget +20% | measured | 0.42 | -587 / 7 / 490 | -435 / 338 | -183 |
| outcomes_v1-cannibalization-02 | budget +20% | measured | 0.31 | -718 / -156 / 463 | -551 / 296 | 18 |
| outcomes_v1-cannibalization-04 | budget +20% | measured | 0.29 | -1661 / -749 / 539 | -1351 / 229 | -996 |
| outcomes_v1-cpa_drift-01 | budget +20% | measured | 0.28 | -630 / 792 / 2364 | -208 / 1942 | 140 |
| outcomes_v1-cpa_drift-03 | budget +20% | abstained | 0.57 | the pre-period fit is too weak | 206 / 1121 | -155 |
| outcomes_v1-cpa_drift-05 | budget +20% | measured | 0.26 | 106 / 151 / 176 | 116 / 166 | -52 |
| outcomes_v1-fee_increase-02 | budget +20% | measured | 0.26 | -154 / 549 / 1378 | 62 / 1162 | 614 |
| outcomes_v1-fee_increase-04 | budget +20% | measured | 0.26 | -613 / 1382 / 2428 | -185 / 1999 | -2145 |
| outcomes_v1-healthy-01 | budget +20% | measured | 0.42 | -944 / 107 / 1110 | -654 / 820 | 105 |
| outcomes_v1-healthy-03 | budget +20% | measured | 0.32 | -1497 / -258 / 1187 | -1118 / 809 | -235 |
| outcomes_v1-healthy-05 | budget +20% | measured | 0.35 | -375 / -69 / 199 | -294 / 118 | 79 |
| outcomes_v1-healthy-07 | budget +20% | measured | 0.32 | -1217 / -762 / 0 | -1046 / -171 | -586 |
| outcomes_v1-healthy-09 | budget +20% | abstained | 0.53 | the pre-period fit is too weak | 359 / 1216 | -230 |
| outcomes_v1-healthy-11 | budget +20% | measured | 0.35 | -996 / -350 / 783 | -745 / 533 | -693 |
| outcomes_v1-healthy-13 | budget +20% | measured | 0.23 | -1154 / -254 / 793 | -880 / 519 | 66 |
| outcomes_v1-healthy-15 | budget +20% | measured | 0.42 | -1849 / -182 / 770 | -1480 / 401 | -350 |
| outcomes_v1-healthy-17 | budget +20% | measured | 0.26 | -700 / 341 / 1190 | -434 / 924 | 447 |
| outcomes_v1-healthy-19 | budget +20% | measured | 0.22 | -434 / 744 / 2005 | -91 / 1662 | 2110 |
| outcomes_v1-healthy-21 | budget +20% | measured | 0.22 | -905 / 45 / 1641 | -546 / 1282 | 24 |
| outcomes_v1-healthy-23 | budget +20% | measured | 0.31 | -1248 / -386 / 423 | -1012 / 188 | -200 |
| outcomes_v1-healthy-25 | budget +20% | measured | 0.33 | -1046 / -341 / 229 | -866 / 50 | -266 |
| outcomes_v1-healthy-27 | budget +20% | measured | 0.32 | -1332 / 137 / 1336 | -956 / 960 | 77 |
| outcomes_v1-healthy-29 | budget +20% | measured | 0.43 | -1590 / -662 / 876 | -1243 / 528 | -176 |
| outcomes_v1-mix_shift-01 | budget +20% | abstained | 0.50 | the pre-period fit is too weak | -303 / 383 | -420 |
| outcomes_v1-mix_shift-03 | budget +20% | measured | 0.29 | -1221 / -505 / 332 | -1002 / 113 | -328 |
| outcomes_v1-mix_shift-05 | budget +20% | measured | 0.26 | -716 / 180 / 1154 | -452 / 890 | -53 |
| outcomes_v1-refund_spike-02 | budget +20% | measured | 0.36 | 89 / 1007 / 2485 | 427 / 2147 | -734 |
| outcomes_v1-refund_spike-04 | budget +20% | measured | 0.28 | -935 / -184 / 366 | -751 / 183 | 130 |
| outcomes_v1-stockout_on_promoted-01 | budget +20% | measured | 0.31 | -80 / 909 / 1912 | 201 / 1631 | -472 |
| outcomes_v1-stockout_on_promoted-03 | budget +20% | measured | 0.28 | -1970 / -1217 / -586 | -1775 / -781 | 292 |
| outcomes_v1-stockout_on_promoted-05 | budget +20% | abstained | 0.63 | the pre-period fit is too weak | 321 / 1341 | 632 |
| outcomes_v1-supplier_cost_increase-02 | budget +20% | measured | 0.37 | -853 / 409 / 1251 | -556 / 955 | 150 |
| outcomes_v1-supplier_cost_increase-04 | budget +20% | measured | 0.28 | 50 / 1109 / 2148 | 346 / 1852 | 380 |
| outcomes_v1-tracking_break-01 | budget +20% | measured | 0.47 | -924 / 110 / 1403 | -596 / 1075 | -83 |
| outcomes_v1-tracking_break-03 | budget +20% | measured | 0.35 | -338 / 421 / 1015 | -147 / 824 | -442 |
| outcomes_v1-tracking_break-05 | budget +20% | measured | 0.44 | 681 / 1402 / 2250 | 902 / 2029 | 354 |
