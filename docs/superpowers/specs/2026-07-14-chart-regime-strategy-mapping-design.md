# Chart-Regime Strategy Mapping Design

## Goal

Build a BTCUSDT research and runtime pipeline that classifies the preceding seven days of market behavior without using strategy performance, measures which existing or deferred strategy works reliably in the following seven days, maps eligible strategies to chart clusters, and selects the mapped strategy through the existing scheduler-driven trading path.

The live-equivalent selector establishes an initial strategy from the latest seven-day window, reassesses every four hours, and switches only after the same new cluster is observed twice consecutively. A cluster with no statistically credible strategy maps to cash rather than to a forced choice.

## Scope

The first implementation covers BTCUSDT only and reuses the repository's existing strategy catalog, deferred-strategy registry, scheduler-driven backtest, fee and slippage model, position management, and historical feature caches.

The work includes:

- seven-day chart-feature extraction;
- K-Means and Gaussian mixture model (GMM) comparison;
- time-safe cluster training and assignment;
- conditional strategy-performance measurement over the subsequent seven days;
- cluster-to-strategy mapping with an explicit cash outcome;
- a dynamic strategy-selection use case and persisted selection state;
- scheduler-driven walk-forward evaluation and comparison artifacts.

It does not include multi-symbol training, automatic live deployment, online model fitting from live outcomes, or tuning against the final test period.

## Core Temporal Contract

For an anchor time `t`:

```text
[t - 7 days, t)  -> chart features and cluster assignment
[t, t + 7 days)  -> candidate strategy performance measurement
```

The chart cluster is independent of all strategy outcomes. Candidate outcomes from the second interval are used only to build a mapping after the cluster assignment is fixed.

During evaluation or live-equivalent selection:

```text
[t - 7 days, t) -> trained cluster model -> trained mapping -> active strategy
```

No observation at or after `t` may affect the feature vector, scaler, cluster model, mapping, or selection made at `t`.

## Data Strategy

Use a two-stage data design:

1. Long-history OHLCV windows establish whether candidate chart clusters are stable across different BTC price and volatility eras.
2. The common enriched interval, currently centered on the locally cached 2025-07 through 2026-07 BTCUSDT one-minute data, adds trade count, taker flow, premium, mark/index price, and funding features and permits evaluation of every compatible existing and deferred strategy.

Results must distinguish a long-history-stable cluster definition from a strategy mapping supported only by the shorter enriched interval. A strategy is evaluated only where all of its required point-in-time features are available. Missing feature coverage may reduce the evidence for that strategy but must not be silently imputed from future values.

Historical data provenance, cache identity, feature availability, model configuration, and strategy candidate definitions are recorded in every generated artifact.

## Window Sampling and Leakage Control

Classification windows are generated every four hours so the research data matches the runtime reassessment cadence. Each feature vector summarizes the immediately preceding seven days.

Because adjacent seven-day windows overlap heavily, raw window count is not treated as independent sample count. Training, mapping, and evaluation use chronological blocks. Every train/validation/test boundary has a purge of at least seven days, and confidence estimates use time blocks rather than individual overlapping anchors. Mapping reports include both raw observations and effective non-overlapping evidence counts.

All preprocessing is fold-local:

- missing-value policy is fitted from the training interval only;
- robust scaling is fitted from the training interval only;
- K-Means or GMM is fitted from the training interval only;
- cluster-to-strategy mappings use outcomes wholly contained in the mapping interval;
- the test interval is never used to choose feature definitions, cluster count, thresholds, or strategy mappings.

## Chart Features

Each seven-day window produces approximately 25 to 35 interpretable, scale-free features. The initial feature families are:

- returns over 4-hour, 12-hour, 1-day, 3-day, and 7-day horizons;
- realized volatility at multiple horizons and volatility change;
- normalized true range, seven-day high-low range, and close location;
- directional efficiency, defined from net movement relative to total path movement;
- directional run duration, reversal frequency, and return autocorrelation;
- maximum favorable excursion and maximum drawdown within the window;
- breakout frequency and volatility compression or expansion measures;
- normalized candle body and wick structure;
- normalized volume, trade-count, and activity concentration measures;
- taker imbalance summaries where point-in-time coverage exists;
- premium, mark-index basis, and funding summaries where coverage exists;
- explicit availability indicators for optional feature families.

Absolute BTC price is excluded. Features use returns, ratios, robust normalized values, or bounded statistics so clusters do not merely separate historical price levels.

PCA is not part of the primary path because direct features are easier to explain and audit. It may be included only as a separately reported sensitivity experiment.

## Cluster Model Selection

K-Means is the deterministic baseline. GMM is the primary candidate because posterior probabilities provide an operational confidence signal and describe overlapping market states better than hard Euclidean partitions.

Candidate cluster counts from three through eight are compared using training-only criteria:

- cluster-size balance and minimum effective sample count;
- stability across time blocks and random initializations;
- separation and information criteria appropriate to the model;
- interpretable feature summaries;
- rate of low-confidence assignments.

Strategy returns are not used to select the clustering algorithm or cluster count.

Numeric cluster labels are not considered stable identifiers. Artifacts retain model version, centroid or component parameters, feature summaries, and a deterministic component fingerprint. Walk-forward folds may refit their own models; mapping and evaluation always use the model belonging to that fold.

## Conditional Strategy Evaluation

Once clusters are assigned, all eligible existing and deferred candidates are evaluated through the scheduler-driven backtest for the subsequent seven-day interval. Reopening a deferred candidate in this experiment is explicit and limited to testing the new conditional-regime hypothesis; it does not remove or weaken the deferred registry policy for ordinary research.

Strategy statistics are aggregated by chart cluster using time blocks. The mapping score considers:

- net return after the configured Binance fees and slippage;
- maximum drawdown;
- total and effective trade counts;
- consistency across distinct chronological blocks;
- dependence on a small number of outlier trades;
- performance relative to cash, the current adopted fixed strategy, and the best globally selected fixed strategy;
- a conservative uncertainty penalty or lower confidence estimate.

A strategy is eligible for mapping only when it passes explicit minimum effective-window and trade-count thresholds, has positive conservative net evidence, and is not dominated by cash after costs. Exact numeric thresholds are selected using training and validation evidence and then frozen before the final test.

If no strategy qualifies, the cluster maps to cash. The pipeline must never select the least-bad strategy merely because every cluster requires a strategy ID.

## Mapping Artifact

The versioned mapping artifact contains:

- symbol and timeframe;
- feature schema and seven-day lookback;
- preprocessing and cluster-model identity;
- cluster fingerprints and descriptive summaries;
- mapped strategy ID or explicit cash value per cluster;
- selection score, evidence counts, trade counts, return, and drawdown statistics;
- eligibility thresholds and rejection reasons;
- training and validation boundaries;
- candidate-definition and data-provenance hashes.

Loading rejects artifacts whose feature schema, symbol, cluster-model fingerprint, strategy definition, or required provenance is incompatible with the runtime context.

## Dynamic Strategy Selection

A dedicated application use case accepts the current time, recent point-in-time market data, a trained cluster artifact, a trained mapping artifact, and the previous selection state. It returns the active strategy decision and the next immutable selection state.

Selection state records:

- current cluster fingerprint and active strategy ID or cash;
- pending candidate cluster and consecutive observation count;
- last evaluation and switch timestamps;
- model and mapping versions;
- assignment confidence and decision reason.

The transition rules are:

1. On initial startup with sufficient data, classify the latest seven days and immediately select its mapped strategy or cash.
2. Reassess only on a four-hour boundary.
3. Retain the current strategy when the current cluster remains dominant.
4. When a different cluster is dominant with sufficient confidence and separation, record it as pending.
5. Switch only after the same new cluster is observed on two consecutive reassessments.
6. Reset the pending count when the candidate disappears, changes, or falls below confidence requirements.
7. A confirmed cluster mapped to cash disables new entries.
8. Existing positions remain owned by their entry strategy and continue through its established exit and risk-management path.
9. A new active strategy applies only to new entry decisions after the switch.
10. Missing history, incompatible artifacts, unavailable required features, invalid state, or model failure fails closed to no new entry and produces an auditable reason.

The weekly boundary remains an operational reporting and artifact-refresh boundary. It does not override the two-observation transition rule for an already running selector. Model or mapping replacement is an explicit versioned event rather than an implicit consequence of a clock boundary.

## Scheduler and Backtest Integration

The strategy-lifecycle scheduler invokes model and mapping research workflows. The trade scheduler invokes dynamic selection before generating a new entry signal. The selected strategy is resolved through the existing strategy catalog so the selector does not construct strategy implementations directly.

The scheduler-driven walk-forward flow for each fold is:

```text
historical training blocks
  -> fit preprocessing and cluster model
  -> assign training/mapping clusters
  -> run all eligible strategies in subsequent seven-day episodes
  -> build and freeze the cluster-strategy mapping

future test block
  -> replay one-minute market events
  -> reassess cluster on four-hour boundaries
  -> apply two-observation transition state machine
  -> route new entries to the selected catalog strategy or cash
  -> retain existing position ownership and normal exits
  -> record fills, costs, state changes, and performance
```

The backtest uses the same application use case, state transition rules, strategy catalog, trade scheduler, risk policy, position sizing, TP/SL behavior, feature-provider boundary, and cost model intended for runtime composition. Research-only orchestration may prepare artifacts but may not bypass the scheduler when producing final selection-system results.

## Evaluation and Adoption Gate

The same untouched future intervals compare:

- cash;
- the current adopted fixed strategy;
- the best globally selected fixed strategy using training data only;
- the existing hand-authored regime router;
- K-Means dynamic selection;
- GMM dynamic selection.

Reports include:

- compounded net return and maximum drawdown;
- trade count, trades per day, win rate, and net trade expectancy;
- fold-by-fold returns and the number of positive folds;
- time spent in each cluster and in cash;
- cluster assignment confidence and low-confidence frequency;
- strategy selection and switch counts;
- performance by selected cluster and strategy;
- contribution of cash decisions and the effect of switching costs;
- feature, model, mapping, candidate, and data provenance.

The dynamic system is not adopted merely because it has the highest aggregate return. It must improve cost-adjusted untouched OOS behavior without an unacceptable drawdown increase, avoid dependence on a single fold or a few trades, maintain usable cluster stability, and avoid pathological strategy turnover. The initial implementation reports evidence and does not automatically alter live configuration.

If the experiment fails, the negative result and artifacts remain. Cluster count, thresholds, and scores are not retuned on the final test. A new attempt requires a new hypothesis and a separately reserved OOS interval.

## Error Handling and Observability

Research commands fail with explicit errors for invalid boundaries, insufficient purge, incompatible schemas, duplicate candidates, missing strategy definitions, malformed artifacts, or impossible point-in-time feature timestamps.

Runtime-equivalent selection fails closed to cash for insufficient history, low-confidence initial classification, unavailable required inputs, artifact mismatch, or inference failure. It emits structured events for classification, pending transitions, confirmed switches, cash decisions, artifact versions, and rejection reasons. No error path silently falls back to an unrelated default strategy.

## Testing

Unit tests cover:

- feature calculations and scale invariance;
- strict `[t - 7 days, t)` boundaries;
- point-in-time availability and no future fill;
- fold-local preprocessing and model fitting;
- purged chronological splits and effective evidence counts;
- cluster selection independent of strategy returns;
- conditional statistics and conservative eligibility;
- mandatory cash mapping when no strategy qualifies;
- artifact compatibility and deterministic serialization;
- four-hour gating, consecutive confirmation, pending reset, and cash transitions;
- existing-position ownership across a strategy switch;
- fail-closed behavior and auditable decision reasons.

Integration tests cover:

- artifact preparation from historical BTCUSDT fixtures;
- catalog resolution for existing and explicitly included deferred candidates;
- dynamic selection through the real scheduler boundary;
- scheduler-driven fill, cost, risk, and exit behavior after switches;
- walk-forward isolation between training, mapping, and test intervals;
- deterministic result and provenance artifact generation.

The final verification runs the focused unit and integration suites, the existing scheduler and walk-forward regression suites, and a BTCUSDT end-to-end walk-forward command that produces machine-readable and human-readable reports.

## Deliverables

- chart-feature and cluster-model domain/application boundaries;
- research commands for cluster comparison and conditional mapping;
- a versioned model and mapping artifact format;
- a dynamic strategy-selection use case and state model;
- scheduler and runtime composition integration;
- scheduler-driven dynamic-selection walk-forward support;
- tests for temporal safety, cash mapping, switching, and integration;
- BTCUSDT experiment artifacts and an evidence-based adoption recommendation.
