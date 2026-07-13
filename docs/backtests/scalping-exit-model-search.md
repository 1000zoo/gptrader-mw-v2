# Scalping Exit Model Search

Cost: Binance USD-M futures taker fee 0.04% per side, adverse slippage 0.02% per side, funding excluded.

| Rank | Candidate | Kind | Train Net | Test Net | Test Avg Net ROE | Test MDD | Test Trades | Test Trades/day |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | fixed-liq-sl0_0100-tp0_0120 | fixed | -0.3286 | -0.0331 | -0.0014 | 0.0910 | 242 | 3.97 |
| 2 | fixed-rangeok-sl0_0100-tp0_0120 | fixed | -0.3286 | -0.0331 | -0.0014 | 0.0910 | 242 | 3.97 |
| 3 | fixed-active-sl0_0100-tp0_0120 | fixed | -0.2420 | -0.0520 | -0.0032 | 0.1002 | 181 | 2.97 |
| 4 | fixed-active-sl0_0100-tp0_0100 | fixed | -0.2717 | -0.0979 | -0.0054 | 0.1049 | 212 | 3.48 |
| 5 | fixed-nofilter-sl0_0100-tp0_0150 | fixed | -0.2097 | -0.0003 | 0.0002 | 0.1102 | 195 | 3.20 |
| 6 | partial_trailing-nofilter-first_tp0_0100-partial_ratio0_7000-sl0_0080-trail0_0040 | partial_trailing | -0.5125 | -0.0305 | -0.0009 | 0.1113 | 342 | 5.61 |
| 7 | partial_trailing-nofilter-first_tp0_0100-partial_ratio0_5000-sl0_0080-trail0_0040 | partial_trailing | -0.5257 | -0.0315 | -0.0009 | 0.1142 | 342 | 5.61 |
| 8 | fixed-active-sl0_0060-tp0_0150 | fixed | -0.4382 | -0.0877 | -0.0046 | 0.1147 | 219 | 3.59 |
| 9 | fixed-active-sl0_0100-tp0_0150 | fixed | -0.1140 | -0.0567 | -0.0041 | 0.1153 | 153 | 2.51 |
| 10 | fixed-nofilter-sl0_0100-tp0_0120 | fixed | -0.3301 | -0.0044 | -0.0000 | 0.1172 | 251 | 4.11 |
| 11 | trailing-liq-activation0_0100-sl0_0080-trail0_0020 | trailing | -0.5085 | -0.0543 | -0.0017 | 0.1173 | 342 | 5.61 |
| 12 | trailing-rangeok-activation0_0100-sl0_0080-trail0_0020 | trailing | -0.5085 | -0.0543 | -0.0017 | 0.1173 | 342 | 5.61 |
| 13 | trailing-nofilter-activation0_0100-sl0_0080-trail0_0040 | trailing | -0.5573 | -0.0341 | -0.0010 | 0.1215 | 342 | 5.61 |
| 14 | trailing-active-activation0_0080-sl0_0080-trail0_0030 | trailing | -0.4521 | -0.1047 | -0.0047 | 0.1282 | 262 | 4.30 |
| 15 | fixed-active-sl0_0060-tp0_0120 | fixed | -0.3930 | -0.0942 | -0.0045 | 0.1284 | 242 | 3.97 |
| 16 | time-active-max_holding_minutes120-sl0_0080-tp0_0100 | time | -0.4688 | -0.1241 | -0.0056 | 0.1313 | 265 | 4.34 |
| 17 | trailing-active-activation0_0100-sl0_0080-trail0_0020 | trailing | -0.2852 | -0.1272 | -0.0065 | 0.1324 | 234 | 3.84 |
| 18 | time-active-max_holding_minutes120-sl0_0080-tp0_0150 | time | -0.4267 | -0.1267 | -0.0065 | 0.1351 | 233 | 3.82 |
| 19 | fixed-nofilter-sl0_0100-tp0_0100 | fixed | -0.5095 | -0.1035 | -0.0038 | 0.1362 | 315 | 5.16 |
| 20 | fixed-active-sl0_0060-tp0_0080 | fixed | -0.5604 | -0.1040 | -0.0038 | 0.1370 | 323 | 5.30 |
| 21 | fixed-active-sl0_0100-tp0_0080 | fixed | -0.4670 | -0.1374 | -0.0067 | 0.1415 | 246 | 4.03 |
| 22 | trailing-liq-activation0_0150-sl0_0080-trail0_0030 | trailing | -0.4590 | -0.0633 | -0.0028 | 0.1416 | 247 | 4.05 |
| 23 | trailing-rangeok-activation0_0150-sl0_0080-trail0_0030 | trailing | -0.4590 | -0.0633 | -0.0028 | 0.1416 | 247 | 4.05 |
| 24 | fixed-liq-sl0_0100-tp0_0100 | fixed | -0.4127 | -0.0635 | -0.0023 | 0.1430 | 302 | 4.95 |
| 25 | fixed-rangeok-sl0_0100-tp0_0100 | fixed | -0.4127 | -0.0635 | -0.0023 | 0.1430 | 302 | 4.95 |

## Family Best

| Kind | Candidate | Train Net | Test Net | Test Avg Net ROE | Test MDD | Test Trades/day |
|---|---|---:|---:|---:|---:|---:|
| fixed | fixed-liq-sl0_0100-tp0_0120 | -0.3286 | -0.0331 | -0.0014 | 0.0910 | 3.97 |
| partial_trailing | partial_trailing-nofilter-first_tp0_0100-partial_ratio0_7000-sl0_0080-trail0_0040 | -0.5125 | -0.0305 | -0.0009 | 0.1113 | 5.61 |
| trailing | trailing-liq-activation0_0100-sl0_0080-trail0_0020 | -0.5085 | -0.0543 | -0.0017 | 0.1173 | 5.61 |
| time | time-active-max_holding_minutes120-sl0_0080-tp0_0100 | -0.4688 | -0.1241 | -0.0056 | 0.1313 | 4.34 |
| atr | atr-active-atr_period60-max_sl0_0120-max_tp0_0150-min_sl0_0040-min_tp0_0040-sl_atr_multiple2_0000-tp_atr_multiple3_0000 | -0.7844 | -0.3312 | -0.0078 | 0.3349 | 9.52 |
