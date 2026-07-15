# BTCUSDT Three-Day Regime Historical Replay Design

## Objective

Determine whether the fixed three-day BTCUSDT cluster models trained on `[2024-07-01T00:00Z, 2026-07-01T00:00Z)` can classify materially older market history without retraining, threshold tuning, or strategy outcomes.

This is a reverse-time out-of-sample diagnostic. It evaluates classification coverage, confidence, extrapolation, balance, and temporal concentration. It does not claim conventional forward out-of-sample performance because the evaluation interval precedes the training interval.

## Fixed Models

Replay exactly two existing candidates from the committed deterministic evidence:

- `gmm-diag-k4`, the more temporally stable coarse model;
- `gmm-diag-k8`, the most descriptively balanced fine-grained model.

Load their complete diagnostic fits from `docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json`. Validate the report kind, schema, registry, interval, content hash, candidate identity, fit fingerprints, shapes, covariance mode, and configuration before assignment.

The replay must use the frozen retained feature names, training clipping bounds, medians, scales, component means, weights, diagonal covariances, distance thresholds, and assignment-probability configuration. It must not refit, relabel, recalibrate, or modify either model.

These remain diagnostic fits and must not be converted into runtime `RegimeModelArtifact` objects or loaded by the live runtime repository.

## Historical Evaluation Interval

- Raw BTCUSDT one-minute OHLCV interval: `[2021-01-01T00:00Z, 2024-07-01T00:00Z)`.
- First feature anchor: `2021-01-04T00:00Z`.
- Last feature anchor: `2024-06-30T00:00Z`.
- Expected daily three-day feature windows: exactly `1,274`.
- Every vector uses only `[anchor-3d, anchor)` closed candles.

The local verified Binance archive cache is reused through the public historical-loader interfaces. Every required archive is checksum-validated and recorded with stable URL, member identity, SHA-256, byte count, and period. Missing minutes, duplicate minutes, checksum failures, wrong archive identity, or any vector count other than 1,274 fail the entire replay.

## Replay Metrics

Calculate the following separately for K=4 and K=8.

### Assignment and confidence

- assigned fingerprint and maximum GMM posterior probability for every anchor;
- probability quantiles and count/share below the model's frozen assignment-probability threshold;
- component distance and count/share above the frozen component distance threshold;
- joint accepted count/share under the existing frozen assignment gates;
- no new threshold chosen from historical data.

Every finite vector receives a nearest/maximum-posterior label for distribution analysis, but labels failing frozen gates are reported as low-confidence or out-of-envelope rather than silently treated as valid classifications.

### Training-envelope extrapolation

Before clipping, compare retained raw feature values with the frozen training lower and upper bounds. Report:

- anchors with at least one retained feature outside the training envelope;
- per-feature lower and upper exceedance counts/shares;
- number of clipped retained dimensions per anchor and its quantiles.

This distinguishes genuine historical coverage from assignments created only after heavy clipping.

### Distribution and dependence

- raw cluster counts, shares, empty-cluster count, normalized entropy, minimum and maximum share;
- calendar-quarter counts for all fourteen quarters from `2021-Q1` through `2024-Q2`;
- quarterly zero-count and concentration warnings;
- three-day circular moving-block bootstrap share intervals with 5,000 resamples, 95% confidence, and seed `20260714`;
- one-hot effective sample sizes through lag 30;
- Jensen-Shannon divergence between the historical assignment distribution and the model's original 727-window training distribution.

Jensen-Shannon divergence is descriptive and uses the common frozen fingerprint order. It does not create an acceptance threshold.

## Interpretation

The report must separate three conclusions:

1. **Coverage:** how often old vectors remain inside the training envelope and pass frozen probability/distance gates.
2. **Balance:** whether all frozen clusters appear with usable prevalence across the whole interval and individual quarters.
3. **Stability:** whether dependence-adjusted sample sizes and training-versus-history prevalence remain informative.

No single arbitrary pass/fail score is introduced. K=4 and K=8 are compared in a compact table, and the report may name a preferred candidate for the later strategy-mapping experiment only when the preference follows the declared lexicographic diagnostic order:

1. higher joint accepted share;
2. lower any-feature clipping share;
3. fewer quarter-level empty-cluster warnings;
4. higher minimum effective sample size;
5. lower Jensen-Shannon divergence;
6. lower cluster count as the final tie-break.

This is a research preference, not production-model selection or adoption.

## Outputs

Generate atomically as a paired report:

- `docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.json`;
- `docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.md`.

The JSON contains stable archive provenance and combined hash, source model/report hashes, exact anchor boundaries, per-anchor classification diagnostics, aggregated metrics, and explicit flags:

- `models_refit: false`;
- `thresholds_recalibrated: false`;
- `strategy_outcomes_read: false`;
- `strategy_outcomes_evaluated: false`;
- `production_model_selected: false`.

The Markdown contains the K=4/K=8 comparison, confidence and clipping diagnostics, quarterly warnings, historical-versus-training distribution changes, and limitations. It must state that the three-day windows overlap, the evaluation is reverse-time rather than forward OOS, and no strategy outcome was evaluated.

## Architecture

Add a dedicated research replay script that reuses:

- the public verified Binance archive loader;
- the existing three-day temporal contract and feature extractor;
- `ClusterDiagnosticFit` validation and `SklearnClusterDiagnostic.assign`;
- Task 4 balance, quarterly, bootstrap, and effective-sample-size services;
- Task 5 canonical serialization and paired atomic publication through a focused shared reporting helper only if extraction does not alter existing report bytes.

Keep source-model loading, historical vector streaming, assignment diagnostics, aggregation, and rendering as separately testable functions. Do not add scheduler, selector, runtime configuration, strategy mapping, or live composition changes.

## Failure Behavior

Fail closed before publishing either report when any of these occur:

- source evidence hash, kind, interval, schema, registry, candidate, fit, or fingerprint mismatch;
- archive checksum, URL/member identity, continuity, symbol, or finite-value failure;
- anchor count other than 1,274;
- retained-feature or assignment dimension mismatch;
- non-finite posterior, distance, divergence, bootstrap, or ESS result;
- report destination alias or partial paired-publication failure.

Technical failure of either K=4 or K=8 fails the replay rather than silently comparing one model.

## Verification

Tests must cover:

- exact 1,274 anchors and half-open boundaries;
- strict source-evidence and fit validation;
- no refit or threshold mutation;
- assignment probability and distance-gate accounting;
- pre-clipping envelope exceedance accounting;
- cluster, quarter, bootstrap, ESS, and Jensen-Shannon calculations;
- deterministic repeated canonical output under the existing single-thread diagnostic boundary;
- archive checksum/gap/duplicate failures;
- paired output rollback and destination-alias rejection;
- direct script `--help` execution;
- unchanged seven-day runtime defaults and artifacts.

After focused and full repository tests pass, run the exact real replay twice from the verified cache, require byte-identical JSON and Markdown hashes, independently audit the evidence, and commit only the two generated reports plus any separately reviewed implementation commits.

## Non-Goals

- No strategy backtest, next-day return, cluster-to-strategy mapping, or profitability claim.
- No forward walk-forward evaluation.
- No refitting, label remapping, threshold calibration, or production selection.
- No live runtime activation or scheduler integration.
