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

Implementation is sequenced, not scope-reduced. The K-Means, common-OHLCV, fixed-artifact path is built and verified first so failures are attributable. GMM, confidence transitions, every eligible deferred family, and the complete walk-forward comparison remain required deliverables of this design.

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

All boundaries use UTC. Runtime classification occurs at `00:00`, `04:00`, `08:00`, `12:00`, `16:00`, and `20:00` UTC. An evaluation at `12:00` uses observations whose point-in-time availability is strictly earlier than `12:00`; the candle opening or closing at the boundary is excluded if it was not fully available before the boundary.

Four-hour anchors are classification observations, not independent strategy-outcome evidence. Mapping evidence uses non-overlapping seven-day episodes anchored at Monday `00:00` UTC:

```text
classification observations: every four hours
mapping evidence episodes:   [Monday 00:00, next Monday 00:00)
```

The preceding seven-day feature window at each weekly episode anchor determines the cluster. This deliberately trades sample count for an auditable independent evidence unit.

## Data Strategy

Use a two-stage data design with one normative cluster-feature schema:

1. Long-history OHLCV windows establish whether candidate chart clusters are stable across different BTC price and volatility eras.
2. The common enriched interval, currently centered on the locally cached 2025-07 through 2026-07 BTCUSDT one-minute data, permits evaluation of strategies that require trade count, taker flow, premium, mark/index price, or funding inputs.

The primary K-Means and GMM cluster models use only the OHLCV-derived features available across both stages. Enriched features are strategy inputs, not primary cluster inputs. This keeps long-history and enriched-period assignments in the same state space. An enriched-feature cluster model may be run only as a separately named sensitivity experiment and cannot replace the primary result.

Availability indicators are excluded from the primary clustering distance. Reports still record feature availability by cluster. Any sensitivity model whose clusters are materially explained by coverage period, or whose cluster exists only during one coverage regime, is rejected as unstable.

Results must distinguish a long-history-stable cluster definition from a strategy mapping supported only by the shorter enriched interval. A strategy is evaluated only where all of its required point-in-time features are available. Missing feature coverage may reduce the evidence for that strategy but must not be silently imputed from future values.

Historical data provenance, cache identity, feature availability, model configuration, and strategy candidate definitions are recorded in every generated artifact.

## Window Sampling and Leakage Control

Classification windows are generated every four hours so the research data matches the runtime reassessment cadence. Each feature vector summarizes the immediately preceding seven days.

Because adjacent classification windows overlap heavily, raw classification count is not treated as evidence count. Cluster stability uses chronological blocks, while strategy mapping uses only the fixed non-overlapping weekly episodes defined above. Every cluster-fit, mapping-fit, validation, and test boundary has a purge of at least seven days. Reports include classification counts and independent mapping-episode counts as different fields.

Every walk-forward fold has four ordered intervals supplied explicitly to the runner:

```text
Cluster Fit Interval
  fit missing-value policy, scaler, and cluster model

Mapping Fit Interval
  keep the cluster model fixed
  assign weekly episode anchors
  run candidate strategies and create a candidate mapping

Validation Interval
  keep the cluster model and candidate mapping inputs fixed
  choose from predeclared cluster count, covariance, confidence,
  evidence, and eligibility candidates

Purged Test Interval
  freeze the selected model, mapping, and all thresholds
  evaluate the live-equivalent selector
```

Intervals never overlap and every measured seven-day outcome must end before the next interval's purge begins. Cluster fitting and mapping outcomes may not share an interval. Validation outcomes select only among configurations declared before validation. Before test, the chosen cluster model remains fixed; the mapping statistics may be recomputed from Mapping Fit plus Validation episodes using the already chosen thresholds. The resulting artifacts are frozen before the first test event. The next walk-forward fold may expand and refit all pre-test intervals under the same procedure.

All preprocessing is fold-local:

- missing-value policy is fitted from the Cluster Fit Interval only;
- robust scaling is fitted from the Cluster Fit Interval only;
- K-Means or GMM is fitted from the Cluster Fit Interval only;
- cluster-to-strategy mappings use outcomes wholly contained in Mapping Fit or, after configuration selection, Validation;
- the test interval is never used to choose feature definitions, cluster count, thresholds, or strategy mappings.

## Chart Features

Each seven-day window produces approximately 25 to 35 interpretable, scale-free OHLCV features. A versioned feature registry defines every feature's name, exact formula, input columns, aggregation timeframe, lookback, timestamp-availability rule, null policy, clipping policy, scale-invariance property, and schema version. Implementations may not substitute a semantically similar formula without changing the schema version.

The initial feature families are:

- returns over 4-hour, 12-hour, 1-day, 3-day, and 7-day horizons;
- realized volatility at multiple horizons and volatility change;
- normalized true range, seven-day high-low range, and close location;
- directional efficiency, defined from net movement relative to total path movement;
- directional run duration, reversal frequency, and return autocorrelation;
- maximum favorable excursion and maximum drawdown within the window;
- breakout frequency and volatility compression or expansion measures;
- normalized candle body and wick structure;
- normalized base and quote volume and volume-concentration measures.

Absolute BTC price is excluded. Features use returns, ratios, robust normalized values, or bounded statistics so clusters do not merely separate historical price levels.

Features are not all calculated directly from noisy one-minute bars. Returns, volatility, path efficiency, reversal, and breakout features use deterministic 15-minute resampling; candle body, wick, and volume-structure features use deterministic one-hour resampling. Resampling uses only fully closed source candles and records the aggregation rule in the registry. Enriched sources retain their native publication cadence when used by strategies.

Within each Cluster Fit Interval, absolute Spearman correlation at or above `0.95` marks a redundant pair. A deterministic registry priority retains one member, and each feature family contributes at most five inputs. The retained feature set is stored in the artifact. A model is rejected if one feature family dominates more than half of the retained dimensions.

PCA is not part of the primary path because direct features are easier to explain and audit. It may be included only as a separately reported sensitivity experiment.

## Cluster Model Selection

K-Means is the deterministic baseline. GMM is the primary candidate because posterior probabilities provide an operational confidence signal and describe overlapping market states better than hard Euclidean partitions. GMM candidates are limited to `diag` and regularized `tied` covariance. Full covariance is excluded from the initial BTC design because 25 to 35 dimensions and limited weekly mapping evidence make it unnecessarily unstable. Singular components, non-convergence, or covariance below the configured regularization floor reject a model.

Candidate cluster counts from three through eight are explored, but the following ordered gates determine eligibility and selection:

1. Every cluster has at least eight non-overlapping Mapping Fit episodes and spans at least three distinct calendar months.
2. Random-seed refits on the same data meet predeclared adjusted Rand index and normalized mutual information floors.
3. Chronological-block refits match components by standardized centroid profile and meet predeclared profile-distance and prevalence-drift floors.
4. GMM low-confidence assignments remain below the predeclared maximum rate.
5. Among surviving models, K-Means silhouette or GMM BIC is compared within its model family, followed by interpretability review.

The validation candidate table contains the exact stability, distance, drift, and confidence floors before Validation is read. Models with six through eight clusters are therefore automatically rejected when the available enriched mapping evidence cannot satisfy the minimum episode gate.

Strategy returns, trade counts, and strategy availability are not used to select the clustering algorithm or cluster count. The thirty-trade gate applies later to a strategy's mapping eligibility, not to the independent chart-cluster definition.

Numeric cluster labels are not considered stable identifiers. Artifacts retain model version, centroid or component parameters, feature summaries, and a deterministic component fingerprint. Walk-forward folds may refit their own models; mapping and evaluation always use the model belonging to that fold.

## Conditional Strategy Evaluation

Once clusters are assigned, all eligible existing and deferred candidates are evaluated through the scheduler-driven backtest for the subsequent non-overlapping seven-day episode. Reopening a deferred candidate in this experiment is explicit and limited to testing the new conditional-regime hypothesis; it does not remove or weaken the deferred registry policy for ordinary research.

Every candidate episode starts flat with the same initial equity, risk budget, position-sizing policy, leverage rule, fee schedule, slippage model, and point-in-time warm-up history. Candidate accounts are isolated from one another. New entries stop at the episode end, and any remaining open position is force-closed at the final available market price with the configured market-close fee and slippage. This forced-close convention is recorded separately and applied identically to every candidate. It keeps weekly mapping episodes independent; the final continuous selector replay does not force-close at weekly boundaries.

Strategy statistics are aggregated by chart cluster using time blocks. The mapping score considers:

- net return after the configured Binance fees and slippage;
- episode maximum drawdown and adverse excursion;
- total and effective trade counts;
- consistency across distinct chronological blocks;
- median and 10th-percentile episode return, worst-block return, downside deviation, and expected shortfall;
- profit factor, exposure-adjusted return, and time in market;
- `top_5_trade_pnl_share`, `top_1_episode_pnl_share`, and return without the best episode;
- performance relative to cash, the current adopted fixed strategy, and the best globally selected fixed strategy;
- a block-bootstrap lower confidence bound corrected for the number of candidate strategies evaluated in that cluster.

A strategy is eligible for mapping only when the cluster has at least eight non-overlapping episodes spanning three calendar months, the strategy closes at least thirty trades, its candidate-count-adjusted block-bootstrap lower confidence bound is positive, and it is not dominated by cash after costs. Bootstrap samples use moving blocks of two consecutive weekly episodes, or fourteen days, to retain short serial dependence; ordinary independent-sample t-tests are prohibited. The resample count, confidence level, and family-wise max-statistic correction are predeclared candidates selected in Validation and frozen before Test.

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
- Cluster Fit, Mapping Fit, Validation, purge, and Test boundaries;
- candidate-definition and data-provenance hashes.

Loading rejects artifacts whose feature schema, symbol, cluster-model fingerprint, strategy definition, or required provenance is incompatible with the runtime context.

## Dynamic Strategy Selection

A dedicated application use case accepts the current time, recent point-in-time market data, a trained cluster artifact, a trained mapping artifact, and the previous selection state. It returns the active strategy decision and the next immutable selection state.

Selection state records:

- current cluster fingerprint and active strategy ID or cash;
- pending candidate cluster and consecutive observation count;
- last evaluation and switch timestamps;
- model and mapping versions;
- assignment confidence and decision reason;
- whether new entries are enabled;
- the last committed UTC evaluation-boundary ID.

For GMM, a classification is high-confidence only when both conditions hold:

```text
dominant_probability >= P_MIN
dominant_probability - second_probability >= MARGIN_MIN
```

`P_MIN` and `MARGIN_MIN` come from the predeclared Validation candidate table and are stored as exact values in the frozen artifact. Posterior entropy is reported as a diagnostic but is not a third hidden decision threshold. K-Means uses its predeclared standardized distance-to-centroid rejection threshold.

The transition rules are:

1. On initial startup with a complete point-in-time seven-day window and a high-confidence classification, immediately select its mapped strategy or cash. Low-confidence startup selects cash and disables new entries.
2. Reassess only on a four-hour boundary.
3. Retain the current strategy when the current cluster remains dominant.
4. When a different cluster meets the model's frozen high-confidence and separation rules, record it as pending.
5. Switch only after the same new cluster is observed on two consecutive reassessments.
6. Reset the pending count and disable new entries on the first low-confidence observation. If the next observation confidently returns to the current cluster, re-enable entries. Two consecutive low-confidence observations transition the selector to cash.
7. A confirmed cluster mapped to cash disables new entries.
8. Existing positions remain owned by their entry strategy and continue through its established exit and risk-management path.
9. A new active strategy applies only to new entry decisions after the switch.
10. Missing history, incompatible artifacts, unavailable required features, invalid state, or model failure fails closed to no new entry and produces an auditable reason.

A cluster transition, strategy transition, and cash transition are separate event types. If two cluster fingerprints map to the same strategy, the cluster transition is recorded but no strategy-switch count or strategy lifecycle event is emitted.

The weekly boundary remains an operational reporting and artifact-refresh boundary. It does not override the two-observation transition rule for an already running selector. Model or mapping replacement is an explicit versioned event rather than an implicit consequence of a clock boundary.

On an artifact-version change, the selector atomically resets the pending candidate, immediately classifies with the new model, preserves the prior active strategy only for ownership of existing positions, and disables new entries. Two consecutive high-confidence observations under the new artifact are required before enabling its mapped strategy or cash decision. An incompatible artifact remains fail-closed and cannot migrate old cluster fingerprints.

Selection persistence is a dedicated atomic state operation rather than the current append-only runtime-record behavior. The operation uses `(symbol, boundary_utc, artifact_version)` as an idempotency key, commits the decision event and next state in one SQLite transaction, returns the prior committed result on scheduler retry, rejects requests older than the last committed boundary, and uses optimistic version checking so concurrent runs cannot increment the confirmation counter twice.

## Scheduler and Backtest Integration

The strategy-lifecycle scheduler invokes model and mapping research workflows. The trade scheduler invokes dynamic selection before generating a new entry signal. The selected strategy is resolved through the existing strategy catalog so the selector does not construct strategy implementations directly.

The scheduler-driven walk-forward flow for each fold is:

```text
historical training blocks
  -> fit preprocessing and cluster model
  -> purge at least seven days
  -> assign fixed weekly Mapping Fit clusters
  -> run all eligible strategies in non-overlapping seven-day episodes
  -> validate only predeclared configurations
  -> recompute and freeze the cluster-strategy mapping before Test

future test block
  -> replay one-minute market events
  -> reassess cluster on four-hour boundaries
  -> apply two-observation transition state machine
  -> route new entries to the selected catalog strategy or cash
  -> retain existing position ownership and normal exits
  -> record fills, costs, state changes, and performance
```

The backtest uses the same application use case, state transition rules, atomic/idempotent selection-state boundary, strategy catalog, trade scheduler, risk policy, position sizing, TP/SL behavior, feature-provider boundary, and cost model intended for runtime composition. Research-only orchestration may prepare artifacts but may not bypass the scheduler when producing final selection-system results.

## Evaluation and Adoption Gate

The same untouched future intervals compare:

- cash;
- the current adopted fixed strategy;
- the best globally selected fixed strategy using training data only;
- the existing hand-authored regime router;
- K-Means dynamic selection;
- GMM dynamic selection.

Reports include:

- compounded net return and portfolio-level maximum drawdown from the continuous replay;
- episode maximum drawdown and adverse excursion used for mapping eligibility;
- trade count, trades per day, profit factor, downside deviation, expected shortfall, exposure-adjusted return, and net trade expectancy;
- median, 10th-percentile, and worst-block return;
- win rate as a diagnostic rather than an adoption criterion;
- fold-by-fold returns and the number of positive folds;
- time spent in each cluster and in cash;
- cluster assignment confidence and low-confidence frequency;
- cluster, strategy, and cash transition counts reported separately;
- performance by selected cluster and strategy;
- top-trade and top-episode PnL concentration;
- contribution of cash decisions, turnover-induced execution cost, cash opportunity cost, and signal-discontinuity cost;
- feature, model, mapping, candidate, and data provenance.

Strategy changes do not carry an invented direct fee because open positions keep their original owner. Any observed cost must be attributed to actual turnover, cash exposure, or signal discontinuity.

The dynamic system is not adopted merely because it has the highest aggregate return. Mapping eligibility is based on weekly episode evidence; adoption is based on the continuous replay's compounded equity, portfolio-level drawdown, turnover, transition effects, and fold consistency. It must improve cost-adjusted untouched OOS behavior without an unacceptable drawdown increase, avoid dependence on a single fold or a few trades, maintain usable cluster stability, and avoid pathological strategy turnover. The initial implementation reports evidence and does not automatically alter live configuration.

If the experiment fails, the negative result and artifacts remain. Cluster count, thresholds, and scores are not retuned on the final test. A new attempt requires a new hypothesis and a separately reserved OOS interval.

## Error Handling and Observability

Research commands fail with explicit errors for invalid boundaries, insufficient purge, incompatible schemas, duplicate candidates, missing strategy definitions, malformed artifacts, or impossible point-in-time feature timestamps.

Runtime-equivalent selection fails closed to cash for insufficient history, low-confidence initial classification, unavailable required inputs, artifact mismatch, or inference failure. During an existing strategy state, the first low-confidence inference disables new entries without changing ownership of open positions; the second consecutive low-confidence inference commits cash. It emits structured events for classification, low-confidence entry suspension, pending transitions, cluster transitions, strategy transitions, cash transitions, artifact versions, and rejection reasons. No error path silently falls back to an unrelated default strategy.

## Testing

Unit tests cover:

- feature calculations and scale invariance;
- versioned feature-registry formulas, aggregation timeframes, and correlation pruning;
- strict `[t - 7 days, t)` boundaries;
- UTC four-hour boundaries and exclusion of the boundary candle;
- point-in-time availability and no future fill;
- fold-local preprocessing and model fitting;
- purged four-interval chronological splits and non-overlapping weekly evidence episodes;
- cluster selection independent of strategy returns;
- force-close episode accounting under identical capital, sizing, leverage, risk, and cost settings;
- conditional downside, tail, concentration, and multiple-comparison-adjusted eligibility statistics;
- mandatory cash mapping when no strategy qualifies;
- artifact compatibility and deterministic serialization;
- four-hour gating, consecutive confirmation, low-confidence entry suspension, pending reset, and cash transitions;
- separate cluster and strategy transitions when both clusters map to the same strategy;
- artifact replacement, stale-boundary rejection, optimistic concurrency, and retry idempotency;
- existing-position ownership across a strategy switch;
- fail-closed behavior and auditable decision reasons.

Integration tests cover:

- artifact preparation from historical BTCUSDT fixtures;
- catalog resolution for existing and explicitly included deferred candidates;
- dynamic selection through the real scheduler boundary;
- scheduler-driven fill, cost, risk, and exit behavior after switches;
- walk-forward isolation between training, mapping, and test intervals;
- continuous portfolio-level drawdown distinct from episode drawdown;
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

## Implementation Sequence

The implementation plan uses checkpoints while retaining the full deliverable:

1. Define the common OHLCV feature registry, UTC sampling, non-overlapping weekly episodes, and explicit four-interval fold boundaries.
2. Build K-Means with three-to-five-cluster baseline candidates, cash mapping, fixed artifacts, and scheduler-driven OOS replay.
3. Add the full three-to-eight exploration gates, GMM `diag`/`tied` candidates, confidence transitions, and stability metrics.
4. Expand conditional evaluation to every eligible existing and explicitly opted-in deferred strategy, including enriched strategy inputs where available.
5. Add block-bootstrap multiple-comparison correction, atomic persisted selection state, artifact replacement, and the complete comparison report.
6. Run the untouched BTCUSDT walk-forward evaluation. Failure at any stage remains evidence and does not authorize narrowing the goal or tuning against Test.
