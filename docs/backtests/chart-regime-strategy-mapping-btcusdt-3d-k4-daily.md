# BTCUSDT three-day K4 daily strategy mapping

The frozen K4 model gates failed, so the experiment stopped at cash before candidate, evidence, mapping, or Test access.

- Status: `failed-model-cash`
- Model attempt: `83e25e21a2bccb5cf14572da000718deae7f3e068c45b2898a26e78cef67101f`
- Cluster Fit anchors: `1641`
- Failed gates: `maximum_distance_exceedance_rate, maximum_matched_centroid_distance`

## Fixed model gates

| Gate | Value | Threshold | Passed |
|---|---:|---:|---:|
| `maximum_distance_exceedance_rate` | 0.04631322364411944 | 0.02 | False |
| `maximum_matched_centroid_distance` | 2.3526219570607076 | 0.5 | False |

## Leakage and execution boundary

- Candidate manifest frozen: `false`
- Evidence ledger opened: `false`
- Strategy mapping built: `false`
- Untouched Test loaded: `false`
- Resulting action: `cash-only`

No strategy performance or backtest result exists for this stopped run.
