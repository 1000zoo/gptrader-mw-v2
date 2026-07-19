# Frozen K4 diagnosis — retained evidence

## Scope and provenance

This record retains the minimum verified evidence for the diagnostic-only frozen primary K4 analysis of `BTCUSDT`, profile `three-day-daily-k4-v1`, using a four-component GMM with `diag` covariance. The fit interval was `[2021-01-01T00:00:00Z, 2025-06-30T00:00:00Z)`. Its 1,641 fixed anchors were split into Half A `[2021-01-01T00:00:00Z, 2023-04-01T00:00:00Z)` with 820 samples and Half B `[2023-04-01T00:00:00Z, 2025-06-30T00:00:00Z)` with 821 samples.

The parent run is `d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af` with manifest SHA-256 `5b65aed30c9a8d7c67cf383df9667d599c9fb2938b95b59813be5235077a0824`. The completion run is `eac28399d7cc4e2ab40823560b451af65b4a72fb46166a12406bd7b0bc1da0c5` with manifest SHA-256 `5229ecbf5426abac36aaed07d359691abc7096d5bf9151d47e0211e5976ab24d`, published in evidence commit `5c5d89f9e39bc0894eec49c7de311df8a5357111`. The completion receipt had `replay_parent_match_verified=true`; an independent audit of the canonical run returned `status=verified`.

## Reproduced failure

The fitted-parameter maximum centroid distance was reproduced exactly as `2.3526219570607076`. Primary-model OOD exceedance was reproduced as `76/1641`, rate `0.04631322364411944`.

## Component 0 OOD cause

Component 0 had 24 OOD exceedances among 409 primary-component-0 assigned samples (`24/409`). Its ordered top-five squared Mahalanobis contribution features, ranked by contributions summed across those 24 OOD samples, were `volume_cv_3d`, `rv_ratio_1d_3d`, `volume_ratio_1d_3d`, `directional_efficiency_3d`, and `max_runup_3d`. The maximum single-feature contribution ratio was `0.06744504448284344` against the fixed `0.50` threshold, the strict volatility-family contribution ratio was `0.18227287037132553` against `0.70`, and the maximum top-1 recurrence ratio was `0.125` against `0.50`; therefore `single_feature_concentration`, `volatility_family_concentration`, and `recurrent_feature_dominance` were all false.

The strict volatility registry family contained only `rv_4h`, `rv_1d`, `rv_3d`, and `rv_ratio_1d_3d`. Range-family and volume-family features were excluded from that aggregation.

## Offset stability

The like-for-like full-sample comparator was `full_sample_empirical_centroid_distance=2.2760051902315195`, with maximum pair Half B primary component 3 to half component 1. Its ordered top-five drift features were `rv_1d`, `volume_cv_3d`, `rv_4h`, `rv_3d`, and `range_ratio_3d`.

With the frozen models, assignments, matching, OOD definition, and full-sample empirical comparator unchanged, maximum drift remained component 3 in `3/3` three-day offsets and `7/7` seven-day offsets. Maximum OOD remained component 0 in `2/3` three-day offsets and `1/7` seven-day offsets. The ordered full-sample top-five drift-feature list matched in `0/3` and `0/7`; the corresponding top-five feature set matched in `2/3` and `0/7`.

## Boundary

The frozen K4 cause diagnosis is complete. No gate was re-evaluated, and no strategy Mapping was performed.
