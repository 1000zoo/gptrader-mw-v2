# BTCUSDT 3-Day Regime Balance Diagnostic Design

## Objective

Determine whether three-day BTCUSDT chart windows form reasonably balanced and chronologically stable clusters before attempting any cluster-to-strategy mapping.

This is an exploratory clustering diagnostic. It does not select a live model, evaluate strategies, or claim untouched out-of-sample trading performance.

## Data and Temporal Contract

- Symbol and timeframe: `BTCUSDT` one-minute candles.
- Data interval: `[2024-07-01T00:00:00Z, 2026-07-01T00:00:00Z)`.
- Classification anchors occur once per day at `00:00 UTC`.
- The first anchor is `2024-07-04T00:00:00Z` because the first three days are lookback context only.
- The last anchor is `2026-06-30T00:00:00Z` because its following one-day outcome ends at the data boundary.
- Each anchor uses the half-open feature window `[anchor - 3 days, anchor)`.
- Its reserved outcome interval is `[anchor, anchor + 1 day)`.
- This produces exactly 727 daily anchors and 727 non-overlapping one-day outcome intervals.
- Outcome data is not read or scored in this diagnostic. The outcome boundary is recorded now so a later strategy-mapping experiment can reuse the same samples without redefining time.

The three-day feature windows overlap by two days. Therefore the 727 assignments are reported as raw daily observations but are not treated as 727 independent statistical samples.

## Three-Day Feature Schema

The existing seven-day schema remains unchanged. This experiment introduces a separate schema, `btc-chart-regime-ohlcv-3d-v1`.

All features are strategy-independent and derived only from closed OHLCV candles available before the anchor. Fifteen-minute aggregation is used for returns, volatility, path, reversal, and breakout behavior. One-hour aggregation is used for candle shape and volume structure.

The schema contains these 28 features:

- returns: 4-hour, 12-hour, 1-day, 2-day, and 3-day return;
- volatility: 4-hour, 1-day, and 3-day realized volatility plus the 1-day/3-day volatility ratio;
- range: 1-day and 3-day ATR ratio, 3-day high-low range ratio, and 3-day close location;
- path behavior: 1-day and 3-day directional efficiency;
- reversal behavior: 1-day and 3-day sign-change rate and lag-one return autocorrelation;
- excursions: 3-day maximum drawdown and maximum run-up;
- structure: 3-day breakout rate and mean body, upper-wick, and lower-wick ratios;
- volume: 3-day volume coefficient of variation, top-decile volume share, and 1-day/3-day volume ratio.

Zero-range aggregated candles contribute zero body and wick ratios under the already established maintenance-candle convention. Wholly degenerate windows remain invalid.

Feature selection is fitted once on all 727 exploratory vectors. Absolute Spearman correlation at or above `0.95` removes the lower-priority feature, each family contributes at most five retained inputs, and no family may dominate more than half of retained dimensions. The retained names and every removal reason are reported.

## Candidate Models

The diagnostic evaluates the existing declared model grid without using strategy returns:

- K-Means with cluster counts 3 through 8;
- GMM with cluster counts 3 through 8 and `diag` or regularized `tied` covariance;
- seeds `20260714`, `20260715`, and `20260716`.

The full two-year interval supplies the exploratory primary fit. Random-seed refits use the same retained feature set. Chronological stability uses disjoint first-half and second-half refits with the primary retained feature order fixed, block-local clipping/scaling, inverse projection into primary coordinates, and Hungarian centroid matching.

No strategy result, following-day return, or Test-period outcome enters model fitting or comparison.

## Balance and Dependence Diagnostics

For every candidate model, the report includes:

- raw cluster counts and shares across all 727 anchors;
- minimum and maximum cluster share;
- normalized entropy, `-sum(p * log(p)) / log(k)`;
- empty-cluster count;
- cluster distribution for each of the eight calendar quarters;
- first-half versus second-half prevalence drift, using the same deterministic chronological split as the refits;
- seed ARI and NMI;
- matched chronological centroid distance;
- K-Means silhouette or GMM BIC as a descriptive family metric.

Dependence is handled explicitly:

- share uncertainty uses a moving-block bootstrap with blocks of three consecutive daily anchors, 5,000 resamples, and 95% intervals;
- no IID confidence interval or independent-sample hypothesis test is reported;
- a per-cluster effective sample size is estimated from the one-hot assignment series using the initial-positive autocorrelation sequence through lag 30;
- the report highlights the minimum per-cluster effective sample size as the conservative value.

The report ranks descriptive balance by normalized entropy descending, minimum share descending, maximum share ascending, and then cluster count ascending. Stability metrics are shown separately. The diagnostic does not automatically choose or freeze a production model and does not invent a pass threshold after seeing the results.

## Outputs

The command writes atomically:

- `docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json`;
- `docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.md`.

The JSON records:

- exact interval and anchor count;
- feature registry and retained-feature decisions;
- model configuration, seed, preprocessing, and data hashes;
- all balance, dependence, quarterly, and stability diagnostics;
- every technical rejection reason;
- Binance archive URLs, checksums, sizes, and coverage;
- explicit flags that following-day strategy outcomes were reserved but not evaluated.

The Markdown presents a compact comparison table, quarterly concentration warnings, the most descriptively balanced candidates, and limitations caused by overlapping windows.

## Architecture and Isolation

The implementation adds a separate research command and a three-day feature registry/extractor. It reuses the existing archive verification, canonical hashing, model fitting, fixed-feature chronological refits, and atomic report utilities.

The existing seven-day runtime, persisted artifacts, scheduler, selector state machine, and live configuration remain unchanged. Three-day artifacts cannot be loaded as seven-day runtime artifacts because their schema identifiers differ.

## Failure Behavior

The diagnostic fails closed on:

- missing, duplicated, unordered, or non-UTC one-minute candles;
- incomplete three-day windows or an anchor count other than 727;
- checksum or feature-schema mismatch;
- non-finite features or model metrics;
- model non-convergence, singular covariance, or invalid cluster assignments;
- report hash or atomic-write failure.

A rejected model remains in the report with its precise reason. The command may complete successfully even if every model is rejected, because reporting that result is the purpose of the diagnostic.

## Verification

Tests cover:

- exact 727 daily anchors and half-open three-day/one-day boundaries;
- no outcome candle entering a feature vector;
- all 28 formulas and closed-candle aggregation;
- preservation of the existing seven-day schema and tests;
- deterministic correlation pruning and model grid expansion;
- cluster counts, entropy, quarterly distributions, moving-block bootstrap, and effective sample size;
- fixed-feature chronological refits and seed stability;
- deterministic hashes and atomic JSON/Markdown output;
- a small end-to-end fixture and the real two-year BTCUSDT run.

## Non-Goals

- No strategy backtest or cluster-to-strategy mapping.
- No live runtime activation or strategy switching.
- No automatic relaxation of balance or stability criteria.
- No claim that overlapping daily assignments are independent.
- No replacement or mutation of the completed seven-day experiment.
