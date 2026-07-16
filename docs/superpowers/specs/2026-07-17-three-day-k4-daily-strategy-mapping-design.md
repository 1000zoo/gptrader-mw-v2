# Three-Day K4 Daily Strategy Mapping Design

## Goal

Build and evaluate a leakage-safe BTCUSDT research pipeline that refits a four-component diagonal Gaussian mixture model from prior data, classifies the immediately preceding three days at each daily UTC boundary, maps statistically credible existing or deferred strategies to the four chart regimes using the following non-overlapping day, and replays the frozen mapping through the real scheduler-driven trading path on an untouched test interval.

The experiment may conclude that any or every cluster maps to cash. It must not force a strategy choice, alter live configuration, promote a strategy, or change the existing seven-day runtime path.

## Approved Decisions

- Model family: fold-local `GMM`, diagonal covariance, exactly `K=4`.
- Classification window: `[t - 3 days, t)` using only fully closed one-minute candles.
- Mapping outcome: `[t, t + 1 day)`.
- Selection cadence: once daily at `00:00 UTC` with immediate strategy/cash activation.
- Candidate universe: all existing, failed, deferred, and superseded candidates explicitly opted into this experiment before Validation or Test is read.
- Evidence gate: strict, multiple-candidate-corrected statistical eligibility with cash fallback.
- Position transition: a strategy change never forces liquidation; the new active strategy may close an existing position only by emitting an opposite signal, while the entry-time TP/SL and maximum holding time remain hard risk ceilings.
- Evaluation shape: one chronological holdout using the common enriched-data interval.
- Deployment: research evidence only; no automatic adoption.

## Architecture

Extend the existing chart-regime walk-forward research pipeline rather than creating a parallel backtest implementation. The extension introduces an explicit `three-day-daily-k4-v1` research mode while reusing:

- the verified Binance archive and feature-cache contracts;
- the three-day chart-feature registry and extractor;
- the sklearn regime model infrastructure;
- the deferred strategy registry and scheduler candidate factories;
- `BuildStrategyMappingUseCase` and versioned model/mapping artifacts;
- `RegimeSelectionScheduler`, `TradeScheduler`, and `ExecuteTradeUseCase`;
- the existing fee, slippage, position sizing, guard, and equity accounting paths;
- deterministic canonical reporting and paired atomic publication.

The production seven-day selector and its default-disabled runtime configuration remain byte-for-byte behaviorally unchanged. Three-day daily behavior is available only through the research CLI and explicit backtest dependencies.

## Chronological Contract

The normative intervals are:

```text
Cluster Fit     [2021-01-01T00:00Z, 2025-06-30T00:00Z)
Purge           [2025-06-30T00:00Z, 2025-07-07T00:00Z)
Mapping Fit     [2025-07-07T00:00Z, 2026-01-01T00:00Z)
Purge           [2026-01-01T00:00Z, 2026-01-04T00:00Z)
Validation      [2026-01-04T00:00Z, 2026-04-01T00:00Z)
Purge           [2026-04-01T00:00Z, 2026-04-04T00:00Z)
Untouched Test  [2026-04-04T00:00Z, 2026-07-01T00:00Z)
```

All boundaries are canonical UTC midnights. The Cluster Fit interval fits the missing-value policy, retained feature names, scaling, and K4 model. Neither Mapping Fit outcomes nor later data may alter the cluster model.

For a daily anchor `t`:

```text
[t - 3 days, t) -> feature extraction and fixed-model cluster assignment
[t, t + 1 day)  -> isolated candidate strategy outcome
```

Daily outcome intervals do not overlap. Adjacent feature windows overlap by two days and are not represented as independent cluster observations. Mapping inference operates on the non-overlapping outcome days and uses block methods to retain short serial dependence.

The three-day purge is the minimum between outcome-bearing phases. The seven-day Cluster Fit-to-Mapping boundary is intentionally more conservative and also aligns with enriched-data availability.

## Data and Provenance

Primary cluster features use only the frozen three-day OHLCV registry. Enriched inputs such as taker flow, premium, mark/index basis, funding, trade count, or positioning are candidate-strategy inputs and never clustering inputs.

Each stage records and validates:

- symbol, timeframe, UTC bounds, first and last usable anchor;
- raw archive URL, member identity, bytes, SHA-256, and combined SHA-256;
- feature-cache schema, shard identity, availability interval, and content hash;
- three-day feature registry and retained feature order;
- candidate definition, required feature set, and canonical definition hash;
- fee, slippage, sizing, leverage, guard, TP/SL, and holding-time configuration;
- code/report schema versions and deterministic random seeds.

A candidate is evaluated only on days for which every required point-in-time input is available. Missing enriched inputs exclude that candidate/day with an auditable reason. They are never forward-filled across publication boundaries or imputed from future observations.

Any archive correction, cache hash mismatch, gap, duplicate, reordered row, incompatible schema, or candidate-definition drift fails closed before model fitting, mapping, or Test replay.

## Fold-Local K4 Model

The cluster configuration is fixed before later intervals are read:

```text
model_type       = gmm
covariance_type  = diag
cluster_count    = 4
random_seed      = 20260714
regularization   = 0.000001
```

The model is refitted only from Cluster Fit vectors. Component identifiers are deterministic fingerprints derived from the fitted component profiles; numeric component indices are not stable identifiers.

Even though K4 was chosen by the prior historical diagnostic, the fold-local model must still pass predeclared technical and stability gates:

- convergence and finite parameters;
- positive weights and covariance at or above the regularization floor;
- every component represented across the Cluster Fit chronology;
- seed-refit adjusted Rand index and normalized mutual information floors;
- chronological-block centroid matching and prevalence-drift floors;
- non-degenerate assignment confidence;
- retained feature-family cap and exact feature registry compatibility.

Strategy returns are never used to fit, reject, relabel, or reorder the K4 components. If the fixed K4 configuration fails its model gates, the dynamic selector is not evaluated and the report records a failed-model/cash result.

## Candidate Universe

The experiment intentionally reopens all current and deferred candidate families because the hypothesis is conditional: a strategy that failed globally may work in a specific chart regime.

Before Mapping Fit is evaluated, the pipeline:

1. expands the public candidate factories;
2. explicitly opts into each deferred group through the deferred registry contract;
3. canonicalizes candidates by `candidate_id`;
4. accepts byte-identical duplicate definitions once;
5. rejects conflicting definitions with the same identifier;
6. freezes the ordered candidate IDs, definition hashes, feature requirements, and a candidate-universe hash.

No candidate may be added, removed, renamed, or retuned after Validation or Test is observed. Deferred registry status is not changed by this experiment.

## Daily Candidate Evidence

Each Mapping Fit and Validation day runs every available candidate through the actual scheduler simulator with an isolated account.

- Every candidate/day starts flat with the same initial equity.
- Warm-up data may precede the day but must be point-in-time available.
- New entries stop at the day end.
- Any remaining position is force-closed at the last available price using the normal market-close fee and slippage.
- Candidate accounts, guards, positions, and equity state do not leak across candidates or daily evidence episodes.
- Continuous Test replay does not force-close at daily selection boundaries.

Evidence stores net return, gross return, fees, trade count, exposure, turnover, maximum drawdown, adverse excursion, profit factor, downside deviation, expected shortfall, median and 10th-percentile daily return, worst block, return without the best day, top-one-day PnL share, top-five-trade PnL share, and chronological coverage.

## Strict Mapping Eligibility

Daily returns remain serially dependent. Eligibility therefore uses a moving-block bootstrap with:

```text
block length      = 7 consecutive daily episodes
resamples         = 5000
confidence        = 0.95
random seed       = 20260714
multiple testing  = within-cluster max-statistic correction over the frozen universe
```

A candidate is eligible for a cluster only when all conditions hold:

- at least 30 non-overlapping daily outcome episodes for that cluster;
- appearances spanning at least three distinct calendar months;
- at least 30 closed trades for that candidate/cluster;
- positive net performance after all costs;
- corrected bootstrap lower confidence bound strictly above zero;
- predeclared worst-block, expected-shortfall, and maximum-drawdown limits;
- positive return after removing the best episode;
- no single episode or five trades dominate beyond the predeclared concentration limits;
- not statistically dominated by cash after costs.

Eligible candidates are ordered lexicographically by:

```text
descending corrected lower bound
descending return without best episode
descending expected shortfall
ascending maximum drawdown
descending median daily return
ascending candidate_id
```

If no candidate qualifies, the mapping entry is explicit cash. A strategy is never selected merely to fill every cluster.

Validation compares only a small predeclared table of risk limits and bootstrap configurations. It cannot introduce a new candidate, model family, cluster count, feature definition, score, or threshold. The selected policy is frozen before Test; Mapping Fit plus Validation evidence may rebuild the final mapping under that frozen policy.

## Daily Scheduler Selection

The continuous Test replay evaluates at each `00:00 UTC` boundary.

1. Read exactly the preceding 4,320 fully closed one-minute candles.
2. Extract the frozen three-day feature vector.
3. Assign the fold-local K4 component.
4. Resolve the frozen mapping entry to a candidate ID or cash.
5. Commit the selection state and auditable transition event.
6. Apply the new decision immediately to subsequent entry evaluations.

There is no two-observation confirmation in this research mode. The three-day feature window provides the intended smoothing. A cluster transition that resolves to the same candidate is recorded as a cluster event but not a strategy-switch event.

Cash disables new entries. Missing history, low confidence under the frozen assignment policy, unknown component, incompatible artifact, unavailable feature provider, stale boundary, or persistence failure also fails closed to no new entry.

## Existing Position Semantics

A strategy or cash transition does not liquidate an existing position.

The position retains immutable entry-time risk ownership fields:

- direction, entry price, quantity, leverage, and margin;
- original TP and SL;
- original maximum holding deadline;
- entry candidate definition hash and guard hash.

Those TP/SL and maximum-holding constraints remain hard ceilings and cannot be loosened by the newly selected strategy.

While a position is open and a non-cash strategy is active, the new strategy runs its normal point-in-time signal calculation in exit-only mode:

- an opposite-direction signal closes the existing position with normal fee and slippage;
- a same-direction signal or no signal leaves it open;
- it cannot pyramid, resize, or reverse the position while it remains open;
- a cash decision emits no discretionary exit, so original hard risk rules continue;
- after an opposite-signal close, no new entry is allowed on the same closed candle; the new strategy may enter from the next fully closed candle.

Each such close records the selection boundary, component fingerprint, previous and active candidate IDs, signal identity/direction, position direction, exit price, costs, PnL, and `active_strategy_opposite_signal` reason.

## Untouched Test Comparisons

The frozen Test replay reports the dynamic policy and these baselines under the same execution costs:

- cash;
- the currently adopted fixed strategy;
- the globally best fixed strategy selected from Mapping Fit and Validation only;
- K4 dynamic mapping with entry-owner-only exits;
- K4 dynamic mapping with active-strategy opposite-signal exits;
- the existing manual regime router.

The report separates total return, net PnL, maximum drawdown, trade count, win rate, profit factor, fees, turnover, exposure, cash share, cluster transitions, strategy transitions, cash transitions, signal attempts, guard skips, opposite-signal exit count, and opposite-signal exit PnL contribution.

The adoption assessment is descriptive and requires, at minimum, positive untouched Test return and credible improvement over cash, the adopted fixed strategy, and the pre-Test-selected best fixed strategy without unacceptable drawdown or concentration. Failure leaves the system unadopted. No live setting is changed.

## Outputs

The deterministic paired research outputs are:

- `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.json`;
- `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily.md`;
- `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json`;
- `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-mapping.json`.

The JSON contains full provenance, interval contracts, candidate universe, model and mapping hashes, daily mapping evidence summaries, frozen thresholds, selection events, trades, equity curves, comparisons, and fail-closed reasons. The Markdown is compact and contains the K4 component summaries, cluster-to-strategy/cash table, eligibility/rejection reasons, untouched Test comparison, active-strategy exit effect, and limitations. It does not embed full model matrices or every per-minute row.

Publication is paired and atomic. Exact, normalized, resolved, reserved, symlink, directory, or special-file destination aliases are rejected before rendering or filesystem mutation. A failed replacement preserves recoverable backups and annotates rollback errors.

## Determinism and Audit

The complete real pipeline runs twice with different external thread limits. JSON, Markdown, model, and mapping files must be byte-identical and have recorded SHA-256 hashes.

An independent audit recomputes:

- archive and cache hashes and coverage;
- all Cluster Fit feature vectors and the K4 fit identity;
- Mapping Fit and Validation daily assignments;
- every candidate/day scheduler result used by the mapping;
- cluster eligibility, bootstrap correction, winner ordering, and cash entries;
- all frozen artifact hashes before first Test classification;
- Test assignments, transitions, trades, opposite-signal exits, equity, MDD, and baselines;
- all report values and safety flags.

The audit must prove that no Test observation affects the model, candidate universe, mapping, thresholds, or best-fixed baseline selection.

## Testing Strategy

Tests cover:

- exact UTC intervals, daily episode construction, three-day anchor exclusion, and purge enforcement;
- fold-local K4-only fit and strategy-outcome independence;
- candidate-universe expansion, deferred opt-in, hash conflicts, and feature availability;
- isolated one-day accounts and deterministic forced close;
- seven-day moving-block bootstrap, max-stat correction, strict eligibility, lexicographic ranking, and cash fallback;
- daily scheduler idempotency, immediate transitions, low-confidence cash, and artifact incompatibility;
- existing-position hard-risk preservation and active-strategy opposite-signal close/no-close behavior;
- no same-candle reversal after an active-strategy exit;
- all baselines and adoption reporting;
- source/cache corruption, non-finite values, report aliasing, rollback, and cleanup-error paths;
- subprocess determinism and full repository regression.

New behavior is implemented test-first. Every production change requires a failing behavior test before implementation.

## Safety and Non-Goals

- No live deployment or strategy promotion.
- No change to `regime_selection_enabled: bool = False`.
- No change to the existing seven-day runtime cadence, confirmation rules, model, or mapping artifacts.
- No online refitting from live strategy outcomes.
- No Test-driven candidate filtering, threshold changes, or manual relabeling.
- No forced strategy mapping when cash is the only credible result.
- No claim that a single chronological holdout proves future profitability.
