# BTCUSDT chart-regime strategy mapping

This is walk-forward research evidence, not a promotion or live-trading claim.

- Symbol/timeframe: BTCUSDT 1m
- Frozen before Test: True
- Test claim status: diagnostic_after_pipeline_defect
- Prior exposure reason: chronological block refits independently re-pruned features; fixed to the frozen primary retained feature set without changing grids or gates
- Candidate universe: d8190b1c0bac8de081861b4bad56c09925d4e47df24a3edd900950154a0087b6

## Test comparisons

- cash: cash; return=0; MDD=0; trades=0
- adopted_fixed: ok; return=-0.0246756695407727598143890612; MDD=0.03696358710989763113089043035; trades=189
- train_selected_fixed: cash; return=0; MDD=0; trades=0
- manual_regime_router: ok; return=0; MDD=0; trades=0
- kmeans_dynamic: cash; return=0; MDD=0; trades=0
- gmm_dynamic: cash; return=0; MDD=0; trades=0

## Frozen models and mappings


## Evidence coverage and diagnostics

- Candidate coverage records: 0
- Rejected model configurations: 18
  - `gmm:3:diag`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability; prevalence_drift
  - `gmm:3:tied`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability
  - `gmm:4:diag`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability; prevalence_drift
  - `gmm:4:tied`: minimum_weekly_episodes; minimum_distinct_months; seed_stability; centroid_stability
  - `gmm:5:diag`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability; prevalence_drift
  - `gmm:5:tied`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability
  - `gmm:6:diag`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability
  - `gmm:6:tied`: minimum_weekly_episodes; minimum_distinct_months; seed_stability; centroid_stability; prevalence_drift
  - `gmm:7:diag`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability
  - `gmm:7:tied`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability; prevalence_drift
  - `gmm:8:diag`: minimum_weekly_episodes; minimum_distinct_months; seed_stability; centroid_stability; prevalence_drift
  - `gmm:8:tied`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability
  - `kmeans:3:none`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability; prevalence_drift; family_metric_validity
  - `kmeans:4:none`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability; prevalence_drift
  - `kmeans:5:none`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability
  - `kmeans:6:none`: minimum_weekly_episodes; minimum_distinct_months; seed_stability; centroid_stability; prevalence_drift
  - `kmeans:7:none`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability; prevalence_drift
  - `kmeans:8:none`: minimum_weekly_episodes; minimum_distinct_months; centroid_stability; prevalence_drift
- Mapping metrics: `{"status": "not_evaluated_no_eligible_model"}`

## Costs and provenance

- Cost model: `{"fee_rate_per_side": "0.0004", "slippage_rate_per_side": "0.0002"}`
- Data provenance hash: `a9642a568a6a4a44f3221a43ed20454fff6a52971738a40be174255acfd8c69a`
